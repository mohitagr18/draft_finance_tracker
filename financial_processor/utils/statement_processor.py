"""Single statement processing utilities."""

import json
import os
from pathlib import Path
from typing import Tuple

from autogen_agentchat.agents import AssistantAgent, CodeExecutorAgent
from autogen_agentchat.teams import RoundRobinGroupChat
from autogen_agentchat.conditions import MaxMessageTermination
from autogen_agentchat.messages import TextMessage
from autogen_ext.code_executors.docker import DockerCommandLineCodeExecutor
from autogen_agentchat.ui import Console

from config.models import get_anthropic_client, get_openai_client
from utils.file_utils import load_statement
from utils.json_utils import extract_json_from_text
from utils.quality_checks import *
from utils.termination_conditions import JSONSuccessTermination, CategorizationSuccessTermination
from agents.prompts.statement_parser_message import STATEMENT_PARSER_SYSTEM_MESSAGE
from agents.prompts.categorizer_message import CATEGORIZER_SYSTEM_MESSAGE
from agents.prompts.task_message import TASK_MESSAGE
from config.constants import TEMP_DIR


async def process_single_statement(file_path: str, output_dir: str, retry_level: int = 0) -> Tuple[bool, str, dict]:
    """
    Process a single statement file.
    Returns: (success: bool, error_message: str, parsed_data: dict)
    """
    try:
        statement_text = load_statement(file_path)
        work_dir = "temp" # same as DockerCommandLineCodeExecutor(work_dir="temp")
        os.makedirs(work_dir, exist_ok=True)
        input_fp = Path(work_dir) / "statement.txt"
        with open(input_fp, "w", encoding="utf-8") as f:
            f.write(statement_text)

        # Create the model client
        model_client = get_anthropic_client()
        # model_client = get_openai_client()

        # Assistant agent: writes code to parse the statement
        assistant = AssistantAgent(
            name="assistant",
            model_client=model_client,
            system_message=STATEMENT_PARSER_SYSTEM_MESSAGE,
            reflect_on_tool_use=True
        )

        # Code executor
        code_executor = DockerCommandLineCodeExecutor(
            work_dir=TEMP_DIR,
            image="amancevice/pandas",  
            # image="demisto/pandas"
            )
        await code_executor.start()

        # Code execution agent
        executor_agent = CodeExecutorAgent(
            name="executor",
            code_executor=code_executor
        )

        # --- Categorizer Agent ---
        categorizer_agent = AssistantAgent(
            name="categorizer",
            model_client=model_client,
            system_message=CATEGORIZER_SYSTEM_MESSAGE,
            reflect_on_tool_use=False
        )

        # STAGE 1: Assistant + Executor to parse the statement
        json_termination = JSONSuccessTermination()
        parsing_team = RoundRobinGroupChat(
            participants=[assistant, executor_agent],
            termination_condition=json_termination
        )

        # Send the statement as initial task

        task = TextMessage(
            content=TASK_MESSAGE,
            source="user"
        )
        # task = TextMessage(
        #     content=f"statement_text = '''{statement_text}'''",
        #     source="user"
        # )

        # task = TextMessage(content=f"""
        #                    You need to write complete Python code that:
        #                     1. Defines the statement_text variable with the bank statement content
        #                     2. Parses the statement text to extract transactions
        #                     3. Returns the data as JSON

        #                     Here is the bank statement content to parse:

        #                     {statement_text}

        #                     Write complete Python code that assigns this content to statement_text and processes it.
        #                     """,
        #                     source="user"
        #                     )

        parsing_result = await Console(parsing_team.run_stream(task=task))

        # Extract JSON from parsing stage
        parsed_json = None
        for msg in parsing_result.messages:
            if getattr(msg, "source", "") == "executor":
                content = getattr(msg, "content", "")
                parsed_json = extract_json_from_text(content)
                if parsed_json:
                    break

        if not parsed_json:
            await code_executor.stop()
            return False, "Failed to parse statement in Stage 1", {}

        # STAGE 2: Categorizer processes the parsed JSON
        categorizer_task = TextMessage(
            content=f"Here is the parsed JSON to categorize:\n```json\n{json.dumps(parsed_json, indent=2)}\n```",
            source="user"
        )

        categorization_termination = CategorizationSuccessTermination()
        max_message_termination = MaxMessageTermination(max_messages=10)
        
        categorizer_team = RoundRobinGroupChat(
            participants=[categorizer_agent],
            termination_condition=categorization_termination | max_message_termination
        )

        categorization_result = await Console(categorizer_team.run_stream(task=categorizer_task))

        # Stop executor safely
        await code_executor.stop()

        # Search categorization result for final JSON
        final_parsed_json = None

        # Check categorizer messages first
        for msg in categorization_result.messages:
            src = getattr(msg, "source", "")
            content = getattr(msg, "content", None)
            try:
                content_str = content if isinstance(content, str) else str(content)
            except Exception:
                content_str = None

            if not content_str:
                continue

            if src == "categorizer":
                final_parsed_json = extract_json_from_text(content_str)
                if final_parsed_json is not None:
                    break

        # Fallback: check all messages
        if final_parsed_json is None:
            for msg in categorization_result.messages:
                content = getattr(msg, "content", None)
                try:
                    content_str = content if isinstance(content, str) else str(content)
                except Exception:
                    content_str = None
                if not content_str:
                    continue
                final_parsed_json = extract_json_from_text(content_str)
                if final_parsed_json is not None:
                    break

        # Use stage 1 result as fallback
        if final_parsed_json is None:
            final_parsed_json = parsed_json

        # Apply the quality gate to validate and clean the result
        # Apply quality gate with the current retry_level
        ok, msg, cleaned_json = quality_gate(statement_text, final_parsed_json, retry_level=retry_level)
        if not ok:
            await code_executor.stop()
            return False, f"Low-quality parse: {msg}", {}
        final_parsed_json = cleaned_json

        # Save individual file result
        filename = Path(file_path).stem
        individual_output_path = Path(output_dir) / f"{filename}_parsed.json"
        with open(individual_output_path, "w", encoding="utf-8") as f:
            json.dump(final_parsed_json, f, indent=2, ensure_ascii=False)

        return True, "", final_parsed_json

    except Exception as e:
        return False, str(e), {}
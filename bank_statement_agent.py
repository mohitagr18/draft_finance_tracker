#!/usr/bin/env python3
import os
import asyncio
import json

from autogen_ext.models.openai import OpenAIChatCompletionClient
from autogen_agentchat.agents import AssistantAgent, CodeExecutorAgent
from autogen_agentchat.teams import RoundRobinGroupChat
from autogen_agentchat.conditions import MaxMessageTermination
from autogen_agentchat.messages import TextMessage
from autogen_ext.code_executors.local import LocalCommandLineCodeExecutor
from dotenv import load_dotenv

load_dotenv()
# === CONFIGURATION ===
BANK_STATEMENT_FILE = "temp/statement.txt"  # Text file containing raw statement
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")  # Or gpt-4, gpt-4o-mini, etc.
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY2")  # Must be set in your environment

if not OPENAI_API_KEY:
    raise EnvironmentError("Please set the OPENAI_API_KEY environment variable.")

# === Helper to read statement text ===
def load_statement(file_path: str) -> str:
    with open(file_path, "r", encoding="utf-8") as f:
        return f.read()

async def run_parsing_agent():
    statement_text = load_statement(BANK_STATEMENT_FILE)

    # Create the model client correctly
    model_client = OpenAIChatCompletionClient(
        model=OPENAI_MODEL, api_key=OPENAI_API_KEY
    )

    # Assistant agent: writes code to parse the statement
    assistant = AssistantAgent(
        name="assistant",
        model_client=model_client,
        system_message=(
            "You are a Python developer assistant. You will receive a raw bank "
            "statement text stored in a variable named `statement`. Write a single "
            "```python``` code block that:\n"
            "1. Parses `statement` into a JSON object with keys: 'transactions' (list of {date, description, amount}), plus 'summary'.\n"
            "2. Prints **only** the JSON via `print(json.dumps(parsed, ensure_ascii=False))`.\n"
            "Do not output any explanation or extra text."
        ),
        reflect_on_tool_use=True
    )

    # Local executor for running the code
    code_executor = LocalCommandLineCodeExecutor(work_dir="agent_exec_workspace")
    await code_executor.start()

    # Code execution agent (runs the assistant’s code)
    executor_agent = CodeExecutorAgent(
        name="executor",
        code_executor=code_executor
    )

    # Round-robin between assistant and executor, terminating after a few turns
    team = RoundRobinGroupChat(
        participants=[assistant, executor_agent],
        termination_condition=MaxMessageTermination(6)
    )

    # Kick off with the raw statement assigned to variable `statement`
    task = TextMessage(
        content=f"statement = '''{statement_text}'''",
        source="user"
    )

    result = await team.run(task=task)

    # Stop the executor safely
    await code_executor.stop()

    # Print only the JSON output from executor
    print("\n=== Parsed JSON Output ===")
    for msg in result.messages:
        if getattr(msg, "source", "") == "executor":
            content = getattr(msg, "content", "")
            if isinstance(content, str) and content.strip().startswith("{"):
                print(content.strip())
                return  # done once we print the JSON

    print("No JSON output detected from executor.")

if __name__ == "__main__":
    asyncio.run(run_parsing_agent())

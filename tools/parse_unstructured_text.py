import asyncio
import json
from autogen_agentchat.agents import AssistantAgent, CodeExecutorAgent
from autogen_agentchat.messages import TextMessage
from agents.prompts.unstructured_text_parser_message import UNSTRUCTURED_TEXT_PARSER_SYSTEM_MESSAGE
from typing import List, Dict

async def parse_unstructured_text(unstructured_text: str, model_client, code_executor_instance) -> str:
    """
    Parses unstructured text by orchestrating a conversational and self-correcting
    process between a code-writing agent and a code-executing agent.

    Args:
        unstructured_text (str): The raw text extracted from a PDF.
        model_client: The language model client for the code-writing agent.
        code_executor_instance: The configured Docker code executor instance.

    Returns:
        str: A JSON string of the extracted transactions, or an error JSON.
    """
    # 1. Define the agents for the conversational sub-task
    code_writer = AssistantAgent(
        name="Code_Writer",
        model_client=model_client,
        system_message=UNSTRUCTURED_TEXT_PARSER_SYSTEM_MESSAGE,
    )

    # Use the CodeExecutorAgent as you suggested. It will initiate the chat and execute code.
    code_executor_agent = CodeExecutorAgent(
        name="Code_Executor",
        code_executor=code_executor_instance
    )

    # 2. Create the initial task message
    task_message = TextMessage(
        content=f"Your task is to parse the following text and extract all financial transactions. "
                f"Follow your system instructions to plan, write, and refine your code until you succeed.\n\n"
                f"--- TEXT TO PARSE ---\n{unstructured_text}\n---",
        recipient=code_writer
    )

    # 3. Run the conversation using the modern streaming method
    chat_history: List[Dict] = []
    async for message in code_executor_agent.run_stream(
        recipient=code_writer,
        messages=[task_message],
    ):
        chat_history.append(message)

    # 4. Extract the final result from the collected chat history
    if not chat_history or len(chat_history) < 2:
        return json.dumps({"error": "Code execution conversation failed."})

    # The final JSON is in the content of the message from the code_writer
    # which is the second to last message in the history.
    final_message = chat_history[-2].get("content", "")
    
    try:
        # The JSON is everything before the "TERMINATE" keyword
        json_string = final_message.split("TERMINATE")[0].strip()
        json.loads(json_string) # Validate that it's proper JSON
        return json_string
    except (json.JSONDecodeError, IndexError):
        return json.dumps({"error": "Could not extract valid JSON from the final message."})




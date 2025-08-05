import asyncio
import json
from autogen_agentchat.agents import AssistantAgent
from tools.parse_csv_tool import parse_csv_file
from tools.extract_text_pdf import extract_text_from_pdf
from tools.parse_unstructured_text import parse_unstructured_text
from tools.standardize_data import standardize_data
from agents.prompts.file_processor_message import FILE_PROCESSOR_SYSTEM_MESSAGE

# --- System Prompt for the File Processor Agent ---
# This prompt acts as the agent's instruction manual or standard operating procedure.


def get_file_processor_agent(model_client, code_executor) -> AssistantAgent:
    """
    Creates and configures the FileProcessorAgent with all its necessary tools.

    This agent acts as an orchestrator, using specialized tools to handle
    different file types and data processing steps.

    Args:
        model_client: The language model client for the agent.
        code_executor: The code executor instance, which is required by the
                               `parse_unstructured_text` tool.

    Returns:
        A configured AssistantAgent ready to process files.
    """

    def parse_unstructured_text_tool(unstructured_text: str) -> str:
        """
        A synchronous wrapper for the async 'parse_unstructured_text' tool.
        This tool parses unstructured text from a PDF by orchestrating a sub-conversation
        between a code-writing agent and a code-executing agent.
        """
        # This wrapper makes the async tool callable by the agent.
        return asyncio.run(
            parse_unstructured_text(unstructured_text, model_client, code_executor)
        )

    # Create a list of all tools for the agent.
    # The wrapper function now has a clear name for the agent to use.
    tools_list = [
        parse_csv_file,
        extract_text_from_pdf,
        parse_unstructured_text_tool,
        # standardize_data 
    ]

    # Pass the list of tools directly to the agent's constructor.
    file_processor_agent = AssistantAgent(
        name="File_Processor_Agent",
        model_client=model_client,
        system_message=FILE_PROCESSOR_SYSTEM_MESSAGE,
        description="An agent that processes CSV and PDF files to extract transaction data.",
        tools=tools_list,
    )

    return file_processor_agent
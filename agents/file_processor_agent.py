import asyncio
import json
from autogen_agentchat.agents import AssistantAgent
from tools.parse_csv_tool import parse_csv_file
from tools.extract_text_pdf import extract_text_from_pdf
from tools.parse_unstructured_text import parse_unstructured_text
from tools.standardize_data import standardize_data
from agents.prompts.file_processor_message import FILE_PROCESSOR_SYSTEM_MESSAGE

def get_file_processor_agent(model_client, code_executor) -> AssistantAgent:
    """
    Creates and configures the FileProcessorAgent with all its necessary tools.

    Args:
        model_client: The language model client for the agent.
        code_executor: The code executor instance, which is required by the
                       `parse_unstructured_text` tool.

    Returns:
        A configured AssistantAgent ready to process files.
    """

    def process_pdf_file(file_path: str) -> str:
        """
        A tool that performs the full PDF processing workflow.
        1. Extracts raw text from the PDF.
        2. Parses the unstructured text into a JSON string of transactions.
        3. Standardizes the transaction data and returns the final JSON string.
        """
        try:
            # Step 1: Extract text using the tool
            unstructured_text = extract_text_from_pdf(file_path)
            if "Error extracting text" in unstructured_text:
                return json.dumps({"error": unstructured_text})

            # Step 2: Parse the unstructured text
            parsed_json_result = asyncio.run(
                parse_unstructured_text(unstructured_text, model_client, code_executor)
            )
            # Check if the result is an error message before standardizing.
            parsed_data = json.loads(parsed_json_result)
            if "error" in parsed_data:
                return parsed_json_result

            # Step 3: Standardize the data using the tool
            final_json = standardize_data(parsed_json_result)
            return final_json

        except Exception as e:
            return json.dumps({"error": f"Failed to process PDF file: {str(e)}"})
    
    # The tool list is now simplified to the two main file-processing tasks
    # and the standalone standardize tool.
    tools_list = [
        parse_csv_file,
        process_pdf_file,
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

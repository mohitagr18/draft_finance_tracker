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

# -----------------------------
# OLD FILE PROCESSOR AGENT 2
# -----------------------------

# import asyncio
# import json
# from autogen_agentchat.agents import AssistantAgent
# from tools.parse_csv_tool import parse_csv_file
# from tools.extract_text_pdf import extract_text_from_pdf
# from tools.parse_unstructured_text import parse_unstructured_text
# from tools.standardize_data import standardize_data
# from agents.prompts.file_processor_message import FILE_PROCESSOR_SYSTEM_MESSAGE

# def get_file_processor_agent(model_client, code_executor) -> AssistantAgent:
#     """
#     Creates and configures the FileProcessorAgent with all its necessary tools.

#     Args:
#         model_client: The language model client for the agent.
#         code_executor: The code executor instance, which is required by the
#                        `parse_unstructured_text` tool.

#     Returns:
#         A configured AssistantAgent ready to process files.
#     """

#     def process_pdf_file(file_path: str) -> str:
#         """
#         A tool that performs the full PDF processing workflow.
#         1. Extracts raw text from the PDF.
#         2. Parses the unstructured text into a JSON string of transactions.
#         3. Standardizes the transaction data and returns the final JSON string.
#         """
#         try:
#             # Step 1: Extract text using the tool
#             unstructured_text = extract_text_from_pdf(file_path)
#             if "Error extracting text" in unstructured_text:
#                 return json.dumps({"error": unstructured_text})

#             # Step 2: Parse the unstructured text using the async wrapper
#             parsed_json_result = parse_unstructured_text_tool(unstructured_text)

#             # Step 3: Standardize the data using the tool
#             final_json = standardize_data(parsed_json_result)
#             return final_json

#         except Exception as e:
#             return json.dumps({"error": f"Failed to process PDF file: {str(e)}"})

#     # This wrapper function is still needed to make the async tool compatible
#     # with the agent's synchronous tool list, but it is now only called internally
#     # by the `process_pdf_file` tool, not directly by the agent.
#     def parse_unstructured_text_tool(unstructured_text: str) -> dict:
#         result = asyncio.run(
#             parse_unstructured_text(unstructured_text, model_client, code_executor)
#         )
#         if isinstance(result, dict) and 'content' in result:
#             result['source'] = "parse_unstructured_text_tool"
#             return result
#         else:
#             return {
#                 "content": result,
#                 "source": "parse_unstructured_text_tool"
#             }

#     # The tool list is now simplified to the two main file-processing tasks.
#     tools_list = [
#         parse_csv_file,
#         process_pdf_file
#         # standardize_data
#     ]

#     # Pass the list of tools directly to the agent's constructor.
#     file_processor_agent = AssistantAgent(
#         name="File_Processor_Agent",
#         model_client=model_client,
#         system_message=FILE_PROCESSOR_SYSTEM_MESSAGE,
#         description="An agent that processes CSV and PDF files to extract transaction data.",
#         tools=tools_list,
#     )

#     return file_processor_agent

# -----------------------------
# OLD FILE PROCESSOR AGENT 1
# -----------------------------
# import asyncio
# import json
# from autogen_agentchat.agents import AssistantAgent
# from tools.parse_csv_tool import parse_csv_file
# from tools.extract_text_pdf import extract_text_from_pdf
# from tools.parse_unstructured_text import parse_unstructured_text
# from tools.standardize_data import standardize_data
# from agents.prompts.file_processor_message import FILE_PROCESSOR_SYSTEM_MESSAGE

# # --- System Prompt for the File Processor Agent ---
# # This prompt acts as the agent's instruction manual or standard operating procedure.


# def get_file_processor_agent(model_client, code_executor) -> AssistantAgent:
#     """
#     Creates and configures the FileProcessorAgent with all its necessary tools.

#     This agent acts as an orchestrator, using specialized tools to handle
#     different file types and data processing steps.

#     Args:
#         model_client: The language model client for the agent.
#         code_executor: The code executor instance, which is required by the
#                                `parse_unstructured_text` tool.

#     Returns:
#         A configured AssistantAgent ready to process files.
#     """

#     def parse_unstructured_text_tool(unstructured_text: str) -> dict:
#         """
#         A synchronous wrapper for the async 'parse_unstructured_text' tool.
#         This tool parses unstructured text from a PDF by orchestrating a sub-conversation
#         between a code-writing agent and a code-executing agent.
#         """
#          # Get the result from the async function
#         result = asyncio.run(
#             parse_unstructured_text(unstructured_text, model_client, code_executor)
#         )
        
#         # Check if result is already a dictionary with a 'content' field
#         if isinstance(result, dict) and 'content' in result:
#             # If so, just add the source field
#             result['source'] = "parse_unstructured_text_tool"
#             return result
#         else:
#             # Otherwise, wrap it in a dictionary with both fields
#             return {
#                 "content": result,
#                 "source": "parse_unstructured_text_tool"
#             }
#         # # This wrapper makes the async tool callable by the agent.
#         # return asyncio.run(
#         #     parse_unstructured_text(unstructured_text, model_client, code_executor)
#         # )
    
#         # This wrapper makes the async tool callable by the agent.
#         # json_string_result = asyncio.run(
#         #     parse_unstructured_text(unstructured_text, model_client, code_executor)
#         # )
        
#         # # This is the crucial change: wrap the result in a dictionary with 'content' and 'source'
#         # return {
#         #     "content": json_string_result,
#         #     "source": "parse_unstructured_text_tool", # You can put a more descriptive name here if you want
#         # }

#     # Create a list of all tools for the agent.
#     # The wrapper function now has a clear name for the agent to use.
#     tools_list = [
#         parse_csv_file,
#         extract_text_from_pdf,
#         parse_unstructured_text_tool
#         # standardize_data 
#     ]

#     # Pass the list of tools directly to the agent's constructor.
#     file_processor_agent = AssistantAgent(
#         name="File_Processor_Agent",
#         model_client=model_client,
#         system_message=FILE_PROCESSOR_SYSTEM_MESSAGE,
#         description="An agent that processes CSV and PDF files to extract transaction data.",
#         tools=tools_list,
#     )

#     return file_processor_agent
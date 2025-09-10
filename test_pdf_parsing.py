"""
AutoGen Bank Statement Parser using CodeExecutorAgent - Latest Version
Agents write and execute code automatically to parse bank statements
"""

import asyncio
import json
import os
from typing import Dict, Any, Union
import pandas as pd

from autogen_agentchat.agents import AssistantAgent, CodeExecutorAgent
from autogen_agentchat.teams import RoundRobinGroupChat
from autogen_agentchat.conditions import MaxMessageTermination
from autogen_ext.models.openai import OpenAIChatCompletionClient
from autogen_ext.code_executors.docker import DockerCommandLineCodeExecutor
from dotenv import load_dotenv

load_dotenv()

async def parse_bank_statement_with_agents(statement_text: str, 
                                          model_config: Dict[str, Any] = None,
                                          output_format: str = "json") -> Union[Dict[str, Any], pd.DataFrame]:
    """
    Parse bank statement using AutoGen agents that write and execute code automatically
    
    Args:
        statement_text: Raw bank statement text
        model_config: Model configuration for agents
        output_format: Output format ("json" or "dataframe")
        
    Returns:
        Parsed transactions as JSON dict or pandas DataFrame
    """
    
    # Create model client
    model_client = OpenAIChatCompletionClient(
        api_key=os.getenv("OPENAI_API_KEY2"),
        model="gpt-4o",
        # max_retries=5
    )
    
    # Create Docker code executor
    code_executor = DockerCommandLineCodeExecutor(work_dir="bank_parsing")
    await code_executor.start()
    
    try:
        # Create coding assistant that generates parsing code
        coder_agent = AssistantAgent(
            name="BankStatementCoder",
            model_client=model_client,
            system_message="""You are an expert Python developer specializing in parsing financial documents.

Your task is to generate Python code that parses bank statement text into structured JSON format.

REQUIREMENTS:
1. Write Python code to parse ALL transactions from the statement text
2. Extract for each transaction: cardholder_name, sale_date, post_date, description, amount
3. Handle multiple cardholders correctly (MOHIT AGGARWAL, HIMANI SOOD, etc.)
4. Handle both positive and negative amounts (payments/credits should be negative)
5. Store the final result in a variable called 'parsing_result' as a JSON structure:
   {
     "transactions": [
       {
         "cardholder_name": "NAME",
         "sale_date": "MM/DD", 
         "post_date": "MM/DD",
         "description": "DESCRIPTION",
         "amount": "XX.XX"  // positive for purchases, negative for payments/credits
       }
     ],
     "summary": {
       "total_transactions": N,
       "cardholders": ["NAME1", "NAME2"],
       "parsing_status": "completed"
     }
   }

PARSING APPROACH:
- Look for cardholder name patterns (all caps names followed by card info)
- Find transaction lines with date patterns MM/DD MM/DD
- Extract amounts with $ signs
- Handle payments/credits (usually have "PAYMENT" or start with -)
- Be thorough - capture every transaction

Write complete working Python code in markdown code blocks. The CodeExecutorAgent will execute it.
Print the final JSON result at the end."""
        )
        
        # Create code executor agent that will run the generated code
        executor_agent = CodeExecutorAgent(
            name="CodeExecutor",
            code_executor=code_executor,
            model_client=model_client,  # Enable it to generate code and execute
            system_message="""You are a code execution specialist that runs Python code to parse bank statements.

Your job is to:
1. Execute Python code provided by other agents
2. Review the parsing results for completeness and accuracy
3. If parsing fails or is incomplete, generate and execute improved code
4. Validate that ALL transactions from the statement are captured
5. Ensure the final JSON structure is correct and complete

When you receive code, execute it and thoroughly check:
- Are all transaction lines parsed?
- Are cardholder names correctly identified?
- Are amounts handled properly (positive/negative)?
- Is the JSON structure complete?

If any issues are found, write and execute corrected code. Do not give up until all transactions are successfully parsed."""
        )
        
        # Create team with both agents
        team = RoundRobinGroupChat([coder_agent, executor_agent])
        
        # Set termination condition
        termination = MaxMessageTermination(max_messages=8)
        
        # Task for agents to complete
        task = f"""
Parse the following bank statement text into structured JSON format using Python code.

The statement contains transaction data for multiple cardholders. Generate and execute Python code that:

1. Parses ALL transactions from the text
2. Extracts cardholder names, dates, descriptions, and amounts
3. Handles positive amounts (purchases) and negative amounts (payments/credits)
4. Returns structured JSON with all transactions

Bank Statement Text:
{statement_text}

BankStatementCoder: Write Python code to parse this data.
CodeExecutor: Execute the code and ensure all transactions are captured correctly.
"""
        
        # Run the team
        result = await team.run(task=task)
        
        # Extract JSON from the conversation result
        final_json = _extract_final_json_from_result(result)
        
        # Convert to requested format
        if output_format.lower() == "dataframe":
            if "transactions" in final_json:
                return pd.DataFrame(final_json["transactions"])
            else:
                return pd.DataFrame()
        
        return final_json
        
    finally:
        # Always stop the code executor
        await code_executor.stop()


def _extract_final_json_from_result(result) -> Dict[str, Any]:
    """
    Extract the final JSON result from the agent conversation
    
    Args:
        result: Result object from AutoGen team execution
        
    Returns:
        Parsed JSON data or error structure if extraction fails
    """
    
    # Try to extract from conversation messages
    messages = getattr(result, 'messages', [])
    
    for message in reversed(messages):  # Start from most recent
        content = getattr(message, 'content', '')
        
        # Look for JSON-like content with parsing_result
        if 'parsing_result' in content and '{' in content:
            try:
                # Try to extract JSON from the message
                json_start = content.find('{')
                json_end = content.rfind('}') + 1
                if json_start != -1 and json_end > json_start:
                    json_str = content[json_start:json_end]
                    parsed_json = json.loads(json_str)
                    if 'transactions' in parsed_json:
                        return parsed_json
            except (json.JSONDecodeError, ValueError):
                continue
        
        # Look for any JSON structure in the content
        if 'transactions' in content and '{' in content:
            try:
                json_start = content.find('{')
                json_end = content.rfind('}') + 1
                if json_start != -1 and json_end > json_start:
                    json_str = content[json_start:json_end]
                    parsed_json = json.loads(json_str)
                    if 'transactions' in parsed_json:
                        return parsed_json
            except (json.JSONDecodeError, ValueError):
                continue
    
    # Return error structure if agents failed to parse
    return {
        "transactions": [],
        "summary": {
            "total_transactions": 0,
            "cardholders": [],
            "parsing_status": "failed"
        },
        "error": "Agents were unable to parse the bank statement. The statement format may be unsupported or the agents need more specific instructions.",
        "conversation_messages": [getattr(msg, 'content', str(msg)) for msg in messages[-3:]]  # Last 3 messages for debugging
    }


# Synchronous wrapper function
def parse_bank_statement_with_autogen_agents(statement_text: str,
                                             model_config: Dict[str, Any] = None, 
                                             output_format: str = "json") -> Union[Dict[str, Any], pd.DataFrame]:
    """
    Synchronous wrapper for parsing bank statements with AutoGen agents
    
    Args:
        statement_text: Raw bank statement text
        model_config: Model configuration dictionary  
        output_format: Output format ("json" or "dataframe")
        
    Returns:
        Parsed transactions in requested format
    """
    
    return asyncio.run(parse_bank_statement_with_agents(statement_text, model_config, output_format))


# Example usage
if __name__ == "__main__":
    
    # Sample bank statement from the provided document
    sample_statement = """
"""

    print("=== AutoGen Bank Statement Parser with CodeExecutorAgent ===")
    print("BankStatementCoder writes Python code, CodeExecutorAgent executes it\n")
    
    # Parse using agents - they write and execute the code automatically
    result = parse_bank_statement_with_autogen_agents(
        statement_text=sample_statement,
        output_format="json"
    )
    
    print("=== Results from Agent-Generated and Executed Code ===")
    print(json.dumps(result, indent=2))
    
    # Also test DataFrame output
    df_result = parse_bank_statement_with_autogen_agents(
        statement_text=sample_statement,
        output_format="dataframe"
    )
    
    print(f"\n=== DataFrame Output ({len(df_result)} transactions) ===")
    if not df_result.empty:
        print(df_result.to_string(index=False))
    else:
        print("No transactions found")
    
    print("\n=== Agent Architecture ===")
    print("1. BankStatementCoder (AssistantAgent):")
    print("   - Generates Python parsing code")
    print("   - Analyzes bank statement structure")
    print("   - Creates regex patterns and parsing logic")
    
    print("\n2. CodeExecutor (CodeExecutorAgent):")
    print("   - Executes the generated Python code using DockerCommandLineCodeExecutor")
    print("   - Can also generate additional code if needed")
    print("   - Validates and fixes parsing results")
    print("   - Ensures all transactions are captured")
    
    print("\n3. Automatic Execution:")
    print("   - Code runs in isolated Docker container")
    print("   - Results automatically captured and returned")
    print("   - No manual intervention required!")

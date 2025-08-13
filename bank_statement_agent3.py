#!/usr/bin/env python3
import os
import asyncio
import json
import re
import logging
from autogen_ext.models.openai import OpenAIChatCompletionClient
from autogen_agentchat.agents import AssistantAgent, CodeExecutorAgent
from autogen_agentchat.teams import RoundRobinGroupChat
from autogen_agentchat.conditions import MaxMessageTermination
from autogen_agentchat.messages import TextMessage
from autogen_ext.code_executors.docker import DockerCommandLineCodeExecutor
from autogen_agentchat.ui import Console
from dotenv import load_dotenv

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("autogen_process.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("bank_statement_parser")

load_dotenv()

# === CONFIGURATION ===
BANK_STATEMENT_FILE = "temp/statement.txt"  # Text file containing raw statement
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")  # Default model
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY2")  # Must be set in your .env

if not OPENAI_API_KEY:
    raise EnvironmentError("Please set the OPENAI_API_KEY2 environment variable.")

# === Helper to read statement text ===
def load_statement(file_path: str) -> str:
    with open(file_path, "r", encoding="utf-8") as f:
        return f.read()

# Improved JSON extraction logic
def extract_json_from_text(text):
    """Extract JSON from text with multiple fallback strategies."""
    if not text or not isinstance(text, str):
        return None
    
    # Strategy 1: Direct parsing if it looks like JSON
    text_clean = text.strip()
    if text_clean.startswith("{") and text_clean.endswith("}"):
        try:
            return json.loads(text_clean)
        except json.JSONDecodeError:
            pass
    
    # Strategy 2: Remove markdown code fences
    text_no_markdown = re.sub(r"```(?:json|python)?", "", text, flags=re.IGNORECASE)
    text_no_markdown = text_no_markdown.strip()
    if text_no_markdown.startswith("{") and text_no_markdown.endswith("}"):
        try:
            return json.loads(text_no_markdown)
        except json.JSONDecodeError:
            pass
    
    # Strategy 3: Find balanced JSON objects
    def find_json_objects(text):
        results = []
        stack = []
        start = -1
        
        for i, char in enumerate(text):
            if char == '{':
                if not stack:
                    start = i
                stack.append(char)
            elif char == '}':
                if stack and stack[-1] == '{':
                    stack.pop()
                    if not stack:  # We've found a complete JSON object
                        try:
                            json_str = text[start:i+1]
                            obj = json.loads(json_str)
                            results.append(obj)
                        except json.JSONDecodeError:
                            pass
        
        return results
    
    json_objects = find_json_objects(text)
    
    # Return the largest JSON object that has transactions_by_cardholder
    valid_jsons = [obj for obj in json_objects if isinstance(obj, dict) and "transactions_by_cardholder" in obj]
    if valid_jsons:
        # Sort by size (number of transactions)
        valid_jsons.sort(key=lambda x: sum(len(txs) for txs in x["transactions_by_cardholder"].values()), reverse=True)
        return valid_jsons[0]
    
    # If we found any JSON objects at all, return the largest one
    if json_objects:
        largest = max(json_objects, key=lambda x: len(json.dumps(x)))
        return largest
    
    return None

# Verification function
def verify_categorized_json(json_data, original_json):
    """Verify that the categorized JSON has all the data from the original."""
    if not json_data or not isinstance(json_data, dict):
        return False
    
    # Check for transactions_by_cardholder
    if "transactions_by_cardholder" not in json_data:
        return False
    
    # Check that we have the same cardholders
    if set(json_data["transactions_by_cardholder"].keys()) != set(original_json["transactions_by_cardholder"].keys()):
        return False
    
    # Check that we have at least the same number of transactions
    for cardholder in original_json["transactions_by_cardholder"]:
        if len(json_data["transactions_by_cardholder"].get(cardholder, [])) < len(original_json["transactions_by_cardholder"][cardholder]):
            return False
    
    # Check that categories were added
    has_categories = False
    for cardholder, transactions in json_data["transactions_by_cardholder"].items():
        if transactions and any("category" in tx for tx in transactions):
            has_categories = True
            break
    
    return has_categories

# Retry logic for categorizer
async def run_categorizer_with_retry(categorizer_agent, parsed_json, max_retries=3):
    """Run the categorizer with retry logic to handle intermittent failures."""
    for attempt in range(max_retries):
        try:
            logger.info(f"Categorization attempt {attempt+1}/{max_retries}...")
            
            categorizer_task = TextMessage(
                content=(
                    f"I need you to categorize all transactions in this JSON data:\n\n"
                    f"{json.dumps(parsed_json, indent=2)}\n\n"
                    f"IMPORTANT INSTRUCTIONS:\n"
                    f"1. Add a 'category' field to EACH transaction using ONLY the 6 predefined categories.\n"
                    f"2. Return the COMPLETE JSON with all data preserved.\n"
                    f"3. Your response should be ONLY the JSON - no explanations or code fences.\n"
                    f"4. Ensure your response is valid JSON that can be parsed directly."
                ),
                source="user"
            )
            
            categorizer_team = RoundRobinGroupChat(
                participants=[categorizer_agent],
                termination_condition=MaxMessageTermination(3)
            )
            
            categorization_result = await categorizer_team.run(task=categorizer_task)
            
            # Extract JSON from the result
            for msg in categorization_result.messages:
                if getattr(msg, "source", "") == "categorizer":
                    content = getattr(msg, "content", "")
                    try:
                        # Try direct parsing first
                        content_cleaned = content.strip()
                        if content_cleaned.startswith("{") and content_cleaned.endswith("}"):
                            result = json.loads(content_cleaned)
                            if result and "transactions_by_cardholder" in result:
                                # Verify categories were added
                                has_categories = False
                                for cardholder, transactions in result["transactions_by_cardholder"].items():
                                    if transactions and any("category" in tx for tx in transactions):
                                        has_categories = True
                                        break
                                
                                if has_categories:
                                    logger.info(f"Successfully categorized on attempt {attempt+1}")
                                    return result
                    except json.JSONDecodeError:
                        pass
            
            logger.warning(f"Attempt {attempt+1} failed to produce valid categorized JSON")
            
        except Exception as e:
            logger.error(f"Error in categorization attempt {attempt+1}: {str(e)}")
    
    # If all retries fail, return the original JSON
    logger.warning("All categorization attempts failed. Returning original JSON.")
    return parsed_json

async def run_parsing_agent():
    statement_text = load_statement(BANK_STATEMENT_FILE)
    
    # Create the model client
    model_client = OpenAIChatCompletionClient(
        model=OPENAI_MODEL, api_key=OPENAI_API_KEY
    )
    
    # Assistant agent: writes code to parse the statement
    assistant = AssistantAgent(
        name="assistant",
        model_client=model_client,
        system_message=(
            "You are a Python developer assistant. You will receive a raw bank "
            "statement text stored in a variable named `statement_text`. Write a single "
            "```python``` code block that:\n"
            "1. Parses `statement_text` into a JSON object with keys:\n"
            "   - 'transactions_by_cardholder': a dictionary where each key is a cardholder name "
            "     and the value is a list of {sale_date, post_date, description, amount}.\n"
            "   - 'summary': contains 'bank_name', 'total_transactions','total_amount','previous_balance','payments','credits','purchases','cash_advances','fees','interest','new_balance', rewards_balance, 'available_credit_limit'.\n"
            "2. Ensure amounts are numbers (floats) and NOT zero.\n"
            "3. Ensure transactions for all cardholders are captured correctly. It is very rare to have no transactions for a cardholder if there are multiple card holders.\n"
            "4. Prints **only** the JSON via `print(json.dumps(parsed, ensure_ascii=False))`.\n"
            "5. IMPORTANT: The variable `statement_text` is already defined - just use it directly.\n"
            "Do not output any explanation or extra text."
        ),
        reflect_on_tool_use=True
    )
    
    # Docker executor for running the code
    code_executor = DockerCommandLineCodeExecutor(work_dir="temp")
    await code_executor.start()
    
    # Code execution agent
    executor_agent = CodeExecutorAgent(
        name="executor",
        code_executor=code_executor
    )
    
    # Categorizer Agent with improved instructions
    categorizer_agent = AssistantAgent(
        name="categorizer",
        model_client=model_client,
        system_message=(
            "You are an AI financial analyst. Your purpose is to categorize financial transactions "
            "into a few broad categories.\n\n"
            "You will receive a JSON object that contains transaction data. Your task is CRITICAL:\n"
            "1. First, ensure you can see the full JSON with all transactions. If it appears incomplete, "
            "   respond with 'INCOMPLETE DATA' and nothing else.\n"
            "2. Add a 'category' field to EACH transaction in the 'transactions_by_cardholder' section.\n"
            "3. Return the COMPLETE JSON with all original data preserved and categories added.\n\n"
            "CRITICAL FORMATTING RULES:\n"
            "- Your response MUST be valid JSON that can be parsed directly.\n"
            "- Do NOT include markdown code fences (```json).\n"
            "- Do NOT include ANY explanatory text before or after the JSON.\n"
            "- Return ONLY the JSON object.\n\n"
            "CATEGORY DEFINITIONS:\n"
            "Food & Dining: All food-related spending including groceries, restaurants, cafes, food delivery.\n"
            "Merchandise & Services: Retail stores, online shopping, electronics, clothing, entertainment.\n"
            "Bills & Subscriptions: Utilities, phone, internet, insurance, recurring services.\n"
            "Travel & Transportation: Costs for getting around. This includes daily transport (gas stations, "
            "Uber, public transit) and long-distance travel (airlines, hotels, rental cars).\n"
            "Financial Transactions: Payments to account, refunds, statement credits, fees, interest.\n"
            "Uncategorized: Transactions that don't clearly fit the above categories.\n"
        ),
        reflect_on_tool_use=False
    )
    
    # STAGE 1: Assistant + Executor to parse the statement
    parsing_team = RoundRobinGroupChat(
        participants=[assistant, executor_agent],
        termination_condition=MaxMessageTermination(25)
    )
    
    # Send the statement as initial task
    task = TextMessage(
        content=f"statement_text = '''{statement_text}'''",
        source="user"
    )
    
    logger.info("Stage 1: Parsing statement...")
    parsing_result = await Console(parsing_team.run_stream(task=task))
    
    # Extract JSON from parsing stage
    parsed_json = None
    executor_output = ""
    
    for msg in parsing_result.messages:
        if getattr(msg, "source", "") == "executor":
            content = getattr(msg, "content", "")
            executor_output = content  # Save for potential fallback
            extracted = extract_json_from_text(content)
            if extracted and isinstance(extracted, dict) and "transactions_by_cardholder" in extracted:
                parsed_json = extracted
                logger.info(f"Found valid JSON with {sum(len(txs) for txs in parsed_json['transactions_by_cardholder'].values())} transactions")
                break
    
    if not parsed_json:
        logger.error("Failed to parse statement in Stage 1")
        raise ValueError("Failed to parse statement in Stage 1")
    
    logger.info("Stage 1 completed successfully. JSON extracted.")
    
    # STAGE 2: Categorizer processes the parsed JSON with retry logic
    logger.info("Stage 2: Categorizing transactions...")
    final_parsed_json = await run_categorizer_with_retry(categorizer_agent, parsed_json)
    
    # Verify the categorized JSON
    if not verify_categorized_json(final_parsed_json, parsed_json):
        logger.warning("Verification failed: categorized JSON is incomplete or missing categories")
        # Try one more time with a direct approach
        try:
            logger.info("Trying direct categorization approach...")
            categorizer_task = TextMessage(
                content=(
                    f"Here is a JSON object with transaction data. Your ONLY task is to add a 'category' field "
                    f"to each transaction in the transactions_by_cardholder section, using the 6 categories "
                    f"defined in your instructions. Return ONLY the complete JSON:\n\n"
                    f"{json.dumps(parsed_json, indent=2)}"
                ),
                source="user"
            )
            
            direct_result = await categorizer_agent.generate_reply(categorizer_task)
            direct_json = extract_json_from_text(direct_result.content)
            
            if direct_json and verify_categorized_json(direct_json, parsed_json):
                logger.info("Direct approach successful!")
                final_parsed_json = direct_json
            else:
                logger.warning("Direct approach failed. Using original parsed JSON.")
                final_parsed_json = parsed_json
        except Exception as e:
            logger.error(f"Error in direct approach: {str(e)}")
            final_parsed_json = parsed_json
    
    # Stop executor safely
    await code_executor.stop()
    
    return final_parsed_json

if __name__ == "__main__":
    try:
        parsed_data = asyncio.run(run_parsing_agent())
        
        logger.info("\n=== Final Parsed JSON Object ===")
        # Check if categories were added
        has_categories = False
        total_transactions = 0
        for cardholder, transactions in parsed_data.get("transactions_by_cardholder", {}).items():
            total_transactions += len(transactions)
            if any("category" in tx for tx in transactions):
                has_categories = True
        
        logger.info(f"Total transactions: {total_transactions}, Categories added: {has_categories}")
        
        # Save the JSON to a file
        output_filename = "parsed_data.json"

    except ValueError as ve:
        logger.error(f"Value Error: {str(ve)}")
        print(f"ERROR: {str(ve)}")
        exit(1)
    except json.JSONDecodeError as je:
        logger.error(f"JSON Decode Error: {str(je)}")
        print(f"JSON Error: {str(je)}")
        exit(1)
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}", exc_info=True)
        print(f"Unexpected error: {str(e)}")
        exit(1)
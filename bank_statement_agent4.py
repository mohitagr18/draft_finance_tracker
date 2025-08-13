#!/usr/bin/env python3
import os
import asyncio
import json
import re
import glob
from pathlib import Path
from autogen_ext.models.openai import OpenAIChatCompletionClient
from autogen_ext.models.anthropic import AnthropicChatCompletionClient
from autogen_agentchat.agents import AssistantAgent, CodeExecutorAgent
from autogen_agentchat.teams import RoundRobinGroupChat
from autogen_agentchat.conditions import MaxMessageTermination, TextMentionTermination
from autogen_agentchat.base import TerminationCondition
from autogen_agentchat.messages import BaseAgentEvent, BaseChatMessage, StopMessage
from typing import Sequence
from autogen_agentchat.messages import TextMessage
from autogen_ext.code_executors.local import LocalCommandLineCodeExecutor
from autogen_ext.code_executors.docker import DockerCommandLineCodeExecutor
from autogen_agentchat.ui import Console
from dotenv import load_dotenv

load_dotenv()

# === CONFIGURATION ===
BANK_STATEMENTS_PATTERN = "temp/statement*.txt"  # Pattern to match multiple statement files
OUTPUT_DIR = "temp/parsed_statements"  # Directory to save individual parsed files
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")  # Default model
# ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-3-5-haiku-latest")  # Default model
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")  # Must be set in your .env

if not ANTHROPIC_API_KEY:
    raise EnvironmentError("Please set the ANTHROPIC_API_KEY environment variable.")

# === Helper to read statement text ===
def load_statement(file_path: str) -> str:
    with open(file_path, "r", encoding="utf-8") as f:
        return f.read()

def ensure_output_dir(output_dir: str):
    """Create output directory if it doesn't exist."""
    Path(output_dir).mkdir(parents=True, exist_ok=True)

def get_statement_files(pattern: str) -> list:
    """Get list of statement files matching the pattern."""
    files = glob.glob(pattern)
    files.sort()  # Sort for consistent processing order
    return files

def combine_parsed_data(individual_files: list) -> dict:
    """Combine multiple parsed JSON files into a single structure."""
    combined = {
        "combined_transactions_by_cardholder": {},
        "individual_statements": [],
        "combined_summary": {
            "total_files_processed": 0,
            "total_transactions": 0,
            "total_amount": 0.0,
            "total_purchases": 0.0,
            "total_payments": 0.0
        }
    }
    
    for file_path in individual_files:
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Add to individual statements
            filename = Path(file_path).stem
            combined["individual_statements"].append({
                "filename": filename,
                "data": data
            })
            
            # Merge transactions by cardholder
            if "transactions_by_cardholder" in data:
                for cardholder, transactions in data["transactions_by_cardholder"].items():
                    if cardholder not in combined["combined_transactions_by_cardholder"]:
                        combined["combined_transactions_by_cardholder"][cardholder] = []
                    combined["combined_transactions_by_cardholder"][cardholder].extend(transactions)
            
            # Update combined summary
            if "summary" in data:
                summary = data["summary"]
                combined["combined_summary"]["total_files_processed"] += 1
                combined["combined_summary"]["total_transactions"] += summary.get("total_transactions", 0)
                combined["combined_summary"]["total_amount"] += summary.get("total_amount", 0)
                combined["combined_summary"]["total_purchases"] += summary.get("purchases", 0)
                combined["combined_summary"]["total_payments"] += summary.get("payments", 0)
                
        except Exception as e:
            print(f"Error reading {file_path}: {e}")
    
    return combined

# ----------------------------
# Robust JSON extraction logic
# ----------------------------
def extract_json_from_text(text: str):
    """Return parsed JSON object found in text or None."""
    if not text or not isinstance(text, str):
        return None

    # strip common code fences
    text2 = re.sub(r"```(?:json|python)?", "", text, flags=re.IGNORECASE)

    # Try quick parse if text is (mostly) JSON
    stripped = text2.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        try:
            return json.loads(stripped)
        except Exception:
            pass

    # Find first balanced {...} substring and try parsing progressively
    start = text2.find("{")
    while start != -1:
        depth = 0
        for i in range(start, len(text2)):
            ch = text2[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    candidate = text2[start:i+1]
                    # try parse
                    try:
                        return json.loads(candidate)
                    except Exception:
                        # parsing failed; continue searching for next '{'
                        break
        start = text2.find("{", start + 1)
    return None

# ----------------------------
# Custom Termination condition classes (following Autogen 0.7.2 pattern)
# ----------------------------
class JSONSuccessTermination(TerminationCondition):
    """Terminates when valid JSON is found in executor output."""
    
    def __init__(self):
        self._terminated = False
    
    @property
    def terminated(self) -> bool:
        return self._terminated
    
    async def __call__(self, messages: Sequence[BaseAgentEvent | BaseChatMessage]) -> StopMessage | None:
        if self._terminated:
            return None
            
        # Check the messages for executor output with valid JSON
        for msg in reversed(messages[-3:]):  # Check last 3 messages
            if getattr(msg, "source", "") == "executor":
                content = getattr(msg, "content", "")
                if extract_json_from_text(content) is not None:
                    self._terminated = True
                    return StopMessage(
                        content="Valid JSON found in executor output.",
                        source="JSONSuccessTermination"
                    )
        return None
    
    async def reset(self) -> None:
        self._terminated = False

def has_categories(json_obj) -> bool:
    """Check if JSON contains categorized transactions."""
    try:
        transactions_by_cardholder = json_obj.get("transactions_by_cardholder", {})
        for cardholder, transactions in transactions_by_cardholder.items():
            if isinstance(transactions, list) and len(transactions) > 0:
                # Check if at least one transaction has a category
                for transaction in transactions:
                    if isinstance(transaction, dict) and "category" in transaction:
                        return True
        return False
    except Exception:
        return False

class CategorizationSuccessTermination(TerminationCondition):
    """Terminates when categorized JSON is found in categorizer output."""
    
    def __init__(self):
        self._terminated = False
    
    @property
    def terminated(self) -> bool:
        return self._terminated
    
    async def __call__(self, messages: Sequence[BaseAgentEvent | BaseChatMessage]) -> StopMessage | None:
        if self._terminated:
            return None
            
        # Check the messages for categorizer output with valid JSON containing categories
        for msg in reversed(messages[-2:]):  # Check last 2 messages
            if getattr(msg, "source", "") == "categorizer":
                content = getattr(msg, "content", "")
                parsed_json = extract_json_from_text(content)
                if parsed_json and has_categories(parsed_json):
                    self._terminated = True
                    return StopMessage(
                        content="Categorized JSON found in categorizer output.",
                        source="CategorizationSuccessTermination"
                    )
        return None
    
    async def reset(self) -> None:
        self._terminated = False

async def process_single_statement(file_path: str, output_dir: str) -> tuple[bool, str, dict]:
    """
    Process a single statement file.
    Returns: (success: bool, error_message: str, parsed_data: dict)
    """
    try:
        statement_text = load_statement(file_path)

        # Create the model client
        model_client = AnthropicChatCompletionClient(
            model=ANTHROPIC_MODEL, api_key=ANTHROPIC_API_KEY)

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
                "Do not output any explanation or extra text. Once the JSON is successfully printed, "
                "you are done - do not continue the conversation."
            ),
            reflect_on_tool_use=True
        )

        # Code executor
        code_executor = DockerCommandLineCodeExecutor(work_dir="temp")
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
            system_message=(
                "You are an AI financial analyst. Your purpose is to categorize financial transactions "
                "into a few broad categories.\n\n"
                "You will receive a JSON object that contains:\n"
                "1. 'transactions_by_cardholder': a dictionary where each key is a cardholder name and "
                "   the value is a list of transaction objects.\n"
                "2. 'summary': a dictionary with account summary data.\n\n"
                "Your job:\n"
                "- Return the exact same JSON object structure.\n"
                "- Do NOT remove or rename any keys.\n"
                "- Do NOT modify the 'summary' section.\n"
                "- Inside 'transactions_by_cardholder', for each transaction object, add a new key-value "
                "  pair: \"category\": \"Category Name\".\n\n"
                "CRITICAL RULES:\n"
                "Use ONLY the 6 categories defined below.\n"
                "For payments, refunds, and fees, use the Financial Transactions category.\n"
                "If a description is too vague, use Uncategorized.\n\n"
                "CATEGORY DEFINITIONS:\n"
                "Food & Dining: All food-related spending. This includes both groceries from supermarkets "
                "and purchases from restaurants, cafes, bars, and food delivery services.\n"
                "Merchandise & Services: A broad category for general shopping and personal care. "
                "This includes retail stores, online marketplaces (like Amazon), electronics, clothing, "
                "hobbies, entertainment, streaming services (Netflix), gym memberships, and drugstores (CVS).\n"
                "Bills & Subscriptions: Recurring charges for essential services. This primarily includes "
                "utilities (phone, internet) and insurance payments.\n"
                "Travel & Transportation: Costs for getting around. This includes daily transport (gas stations, "
                "Uber, public transit) and long-distance travel (airlines, hotels, rental cars).\n"
                "Financial Transactions: All non-spending activities that affect your balance. This includes "
                "payments made to your account, refunds from merchants, statement credits, and any fees or interest charges.\n"
                "Uncategorized: For any transaction that does not clearly fit into the categories above.\n\n"
                "Output ONLY the JSON with categories added. Do not include any explanations or markdown formatting. "
                "Once you output the categorized JSON, you are done - do not continue the conversation."
            ),
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
            content=f"statement_text = '''{statement_text}'''",
            source="user"
        )

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
        categorizer_team = RoundRobinGroupChat(
            participants=[categorizer_agent],
            termination_condition=categorization_termination
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

        # Save individual file result
        filename = Path(file_path).stem
        individual_output_path = Path(output_dir) / f"{filename}_parsed.json"
        with open(individual_output_path, "w", encoding="utf-8") as f:
            json.dump(final_parsed_json, f, indent=2, ensure_ascii=False)

        return True, "", final_parsed_json

    except Exception as e:
        return False, str(e), {}

async def run_parsing_agent():
    """Process multiple statement files."""
    # Get all statement files
    statement_files = get_statement_files(BANK_STATEMENTS_PATTERN)
    
    if not statement_files:
        print(f"No statement files found matching pattern: {BANK_STATEMENTS_PATTERN}")
        return {}
    
    print(f"Found {len(statement_files)} statement file(s): {statement_files}")
    
    # Ensure output directory exists
    ensure_output_dir(OUTPUT_DIR)
    
    successful_files = []
    failed_files = []
    
    # Process each file
    for i, file_path in enumerate(statement_files, 1):
        filename = Path(file_path).name
        print(f"\n[{i}/{len(statement_files)}] Processing: {filename}")
        
        success, error_msg, parsed_data = await process_single_statement(file_path, OUTPUT_DIR)
        
        if success:
            print(f"✓ Successfully processed: {filename}")
            individual_output_path = Path(OUTPUT_DIR) / f"{Path(file_path).stem}_parsed.json"
            successful_files.append(str(individual_output_path))
        else:
            print(f"✗ Failed to process: {filename}")
            print(f"  Error: {error_msg}")
            failed_files.append((filename, error_msg))
    
    # Print summary
    print(f"\n=== Processing Summary ===")
    print(f"Total files: {len(statement_files)}")
    print(f"Successful: {len(successful_files)}")
    print(f"Failed: {len(failed_files)}")
    
    if failed_files:
        print("\nFailed files:")
        for filename, error in failed_files:
            print(f"  - {filename}: {error}")
    
    if successful_files:
        print(f"\nCombining {len(successful_files)} successful results...")
        combined_data = combine_parsed_data(successful_files)
        return combined_data
    else:
        print("No files were successfully processed.")
        return {}

if __name__ == "__main__":
    parsed_data = asyncio.run(run_parsing_agent())
    
    if parsed_data:
        print("\n=== Final Combined JSON Object ===")
        print(json.dumps(parsed_data, indent=2, ensure_ascii=False))

        # Save the combined JSON to a file
        output_filename = "combined_parsed_data.json"
        with open(output_filename, "w", encoding="utf-8") as f:
            json.dump(parsed_data, f, indent=2, ensure_ascii=False)
        
        print(f"\nCombined JSON data saved to {output_filename}")
        print(f"Individual parsed files saved in: {OUTPUT_DIR}/")
    else:
        print("No data to save.")
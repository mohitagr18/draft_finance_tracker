#!/usr/bin/env python3
"""
Complete Financial Statement Processing Pipeline
Combines PDF conversion, statement parsing, and report generation into a single workflow.

Usage:
    python financial_processor.py --input-dir /path/to/pdfs --question "Analyze spending patterns"
    python financial_processor.py --input-dir /path/to/pdfs --question "What is total spending on Food & Dining?"
"""

import pypdf
import os
import asyncio
import json
import re
import glob
import argparse
import shutil
import base64
import sys
import traceback
from pathlib import Path
from typing import List, Sequence
from autogen_ext.models.openai import OpenAIChatCompletionClient
from autogen_ext.models.anthropic import AnthropicChatCompletionClient
from autogen_agentchat.agents import AssistantAgent, CodeExecutorAgent
from autogen_agentchat.teams import RoundRobinGroupChat
from autogen_agentchat.conditions import MaxMessageTermination, TextMentionTermination
from autogen_agentchat.base import TerminationCondition
from autogen_agentchat.messages import BaseAgentEvent, BaseChatMessage, StopMessage, TextMessage
from autogen_ext.code_executors.local import LocalCommandLineCodeExecutor
from autogen_ext.code_executors.docker import DockerCommandLineCodeExecutor
from autogen_agentchat.ui import Console
from dotenv import load_dotenv

load_dotenv()

# === CONFIGURATION ===

# Model configuration
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")  # Fixed typo from original
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY2")

if not ANTHROPIC_API_KEY:
    raise EnvironmentError("Please set the ANTHROPIC_API_KEY environment variable.")
if not OPENAI_API_KEY:
    raise EnvironmentError("Please set the OPENAI_API_KEY2 environment variable.")

TEMP_DIR = "temp"
OUTPUT_DIR = "temp/parsed_statements"
FINAL_OUTPUT_DIR = "output"
COMBINED_JSON_FILE = "combined_parsed_data.json"

# ============================================================================
# STEP 1: PDF CONVERSION (from pdf_converter.py)
# ============================================================================

def convert_pdfs_in_dir(input_dir: str, output_dir: str = TEMP_DIR) -> List[str]:
    """
    Scans a directory for PDF files, extracts text, and saves each to a text file.

    This function searches the specified input directory for any files with a '.pdf'
    extension. It then extracts the text from each PDF and saves it to a new file 
    in the output directory. The output files are named sequentially 
    (e.g., statement1.txt, statement2.txt).

    Args:
        input_dir (str): The path to the directory containing the PDF files.
        output_dir (str): The name of the directory to save the text files.
                          Defaults to 'temp'.

    Returns:
        List[str]: A list of paths to the newly created text files.
                   Returns an empty list if the input directory doesn't exist
                   or contains no PDF files.
    """
    # Check if the input directory exists
    if not os.path.isdir(input_dir):
        print(f"Error: Input directory '{input_dir}' not found.")
        return []

    # Find all files in the directory that end with .pdf (case-insensitive)
    pdf_files = [
        os.path.join(input_dir, filename)
        for filename in os.listdir(input_dir)
        if filename.lower().endswith(".pdf") and os.path.isfile(os.path.join(input_dir, filename))
    ]

    if not pdf_files:
        print(f"No PDF files found in '{input_dir}'.")
        return []

    # Create the output directory if it doesn't exist
    os.makedirs(output_dir, exist_ok=True)
    
    created_text_files = []

    # Enumerate through the list of discovered PDFs to process them
    for i, file_path in enumerate(pdf_files, start=1):
        try:
            print(f"Processing '{file_path}'...")
            reader = pypdf.PdfReader(file_path)
            full_text = ""
            for page in reader.pages:
                page_text = page.extract_text()
                if page_text:
                    full_text += page_text + "\n"
            
            # Define the output file name and path
            output_filename = f"statement{i}.txt"
            output_path = os.path.join(output_dir, output_filename)
            
            # Write the extracted text to the new file
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(full_text)
            
            created_text_files.append(output_path)
            print(f"Successfully created '{output_path}'")

        except Exception as e:
            print(f"Error processing file {file_path}: {str(e)}")
            
    return created_text_files

# ============================================================================
# STEP 2: BANK STATEMENT PARSING (from bank_statement_agent4.py)
# ============================================================================

# === Helper functions ===
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
    """Combine multiple parsed JSON files into a single structure with detailed breakdowns."""
    combined = {
        "combined_transactions_by_cardholder": {},
        "individual_statements": [],
        "combined_summary": {
            "total_files_processed": 0,
            "total_transactions": 0,
            "total_amount": 0.0,
            "total_purchases": 0.0,
            "total_payments": 0.0
        },
        "summary_by_bank": {},
        "summary_by_cardholder": {},
        "category_totals": {}
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
            
            # Get bank name from summary
            bank_name = data.get("summary", {}).get("bank_name", "Unknown Bank")
            
            # Initialize bank summary if not exists
            if bank_name not in combined["summary_by_bank"]:
                combined["summary_by_bank"][bank_name] = {
                    "total_statements": 0,
                    "total_transactions": 0,
                    "total_amount": 0.0,
                    "total_purchases": 0.0,
                    "total_payments": 0.0,
                    "cardholders": []
                }
            
            # Merge transactions by cardholder and calculate totals
            if "transactions_by_cardholder" in data:
                for cardholder, transactions in data["transactions_by_cardholder"].items():
                    # Initialize cardholder in combined transactions
                    if cardholder not in combined["combined_transactions_by_cardholder"]:
                        combined["combined_transactions_by_cardholder"][cardholder] = []
                    combined["combined_transactions_by_cardholder"][cardholder].extend(transactions)
                    
                    # Initialize cardholder summary if not exists
                    if cardholder not in combined["summary_by_cardholder"]:
                        combined["summary_by_cardholder"][cardholder] = {
                            "total_transactions": 0,
                            "total_amount": 0.0,
                            "total_purchases": 0.0,
                            "total_payments": 0.0,
                            "banks": {},
                            "category_totals": {}
                        }
                    
                    # Add cardholder to bank's list if not already there
                    if cardholder not in combined["summary_by_bank"][bank_name]["cardholders"]:
                        combined["summary_by_bank"][bank_name]["cardholders"].append(cardholder)
                    
                    # Initialize bank for this cardholder if not exists
                    if bank_name not in combined["summary_by_cardholder"][cardholder]["banks"]:
                        combined["summary_by_cardholder"][cardholder]["banks"][bank_name] = {
                            "total_transactions": 0,
                            "total_amount": 0.0,
                            "total_purchases": 0.0,
                            "total_payments": 0.0
                        }
                    
                    # Process each transaction
                    cardholder_transaction_count = 0
                    cardholder_total_amount = 0.0
                    cardholder_purchases = 0.0
                    cardholder_payments = 0.0
                    
                    for transaction in transactions:
                        if isinstance(transaction, dict):
                            amount = transaction.get("amount", 0)
                            category = transaction.get("category", "Uncategorized")
                            
                            cardholder_transaction_count += 1
                            cardholder_total_amount += amount
                            
                            # Categorize as purchase or payment (payments are typically negative)
                            if amount < 0:
                                cardholder_payments += abs(amount)
                            else:
                                cardholder_purchases += amount
                            
                            # Update category totals for cardholder
                            if category not in combined["summary_by_cardholder"][cardholder]["category_totals"]:
                                combined["summary_by_cardholder"][cardholder]["category_totals"][category] = 0.0
                            combined["summary_by_cardholder"][cardholder]["category_totals"][category] += amount
                            
                            # Update overall category totals
                            if category not in combined["category_totals"]:
                                combined["category_totals"][category] = 0.0
                            combined["category_totals"][category] += amount
                    
                    # Update cardholder totals
                    combined["summary_by_cardholder"][cardholder]["total_transactions"] += cardholder_transaction_count
                    combined["summary_by_cardholder"][cardholder]["total_amount"] += cardholder_total_amount
                    combined["summary_by_cardholder"][cardholder]["total_purchases"] += cardholder_purchases
                    combined["summary_by_cardholder"][cardholder]["total_payments"] += cardholder_payments
                    
                    # Update cardholder's bank-specific totals
                    combined["summary_by_cardholder"][cardholder]["banks"][bank_name]["total_transactions"] += cardholder_transaction_count
                    combined["summary_by_cardholder"][cardholder]["banks"][bank_name]["total_amount"] += cardholder_total_amount
                    combined["summary_by_cardholder"][cardholder]["banks"][bank_name]["total_purchases"] += cardholder_purchases
                    combined["summary_by_cardholder"][cardholder]["banks"][bank_name]["total_payments"] += cardholder_payments
            
            # Update bank summary from statement summary
            if "summary" in data:
                summary = data["summary"]
                combined["summary_by_bank"][bank_name]["total_statements"] += 1
                combined["summary_by_bank"][bank_name]["total_transactions"] += summary.get("total_transactions", 0)
                combined["summary_by_bank"][bank_name]["total_amount"] += summary.get("total_amount", 0)
                combined["summary_by_bank"][bank_name]["total_purchases"] += summary.get("purchases", 0)
                combined["summary_by_bank"][bank_name]["total_payments"] += summary.get("payments", 0)
                
                # Update combined summary
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
        code_executor = DockerCommandLineCodeExecutor(work_dir=TEMP_DIR)
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

        # Save individual file result
        filename = Path(file_path).stem
        individual_output_path = Path(output_dir) / f"{filename}_parsed.json"
        with open(individual_output_path, "w", encoding="utf-8") as f:
            json.dump(final_parsed_json, f, indent=2, ensure_ascii=False)

        return True, "", final_parsed_json

    except Exception as e:
        return False, str(e), {}

async def run_parsing_agent(statement_files: List[str]) -> dict:
    """Process multiple statement files."""
    
    if not statement_files:
        print(f"No statement files provided for parsing.")
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

# ============================================================================
# STEP 3: REPORT GENERATION (from report_generator3.py)
# ============================================================================

# Data Analyzer System Message
DATA_ANALYZER_SYSTEM_MESSAGE = """
You are a data analyst agent with expertise in financial data analysis, Python, and working with JSON/CSV data. Your primary role is to **write Python code** to analyze financial data and present findings. You will be given a file named `combined_data.json` with the structure outlined below.

```json
{
  "combined_transactions_by_cardholder": {
    "cardholder_name": [
      {
        "sale_date": "YYYY-MM-DD",
        "post_date": "YYYY-MM-DD", 
        "description": "merchant name",
        "amount": 123.45,
        "category": "Food & Dining"
      }
    ]
  },
  "summary_by_bank": { /* ... */ },
  "summary_by_cardholder": { /* ... */ },
  "category_totals": { /* ... */ }
}
```

**CRITICAL EXECUTION REQUIREMENTS:**
- Your Python script MUST always print status messages to verify execution
- Use print() statements liberally to show progress and results
- Always include error handling with try/except blocks that print error messages
- Every script must start with: print("📊 Starting data analysis...")
- Every script must end with: print("✅ Analysis complete!")

Your **first step is to determine if the user's request is broad or specific** and state which workflow you are initiating.

  * A **specific question** has a clear, narrow goal (e.g., "What is the total spending on Food & Dining?", "Who spent the most money?").
  * A **broad question** is open-ended and asks for general exploration (e.g., "Analyze the spending data," "Give me insights on spending patterns.").

You will then follow one of the two workflows below.

---
## Workflow 1: Broad Questions

For broad, open-ended requests, your goal is to generate a **single Python script** that creates a comprehensive, web-friendly markdown report named `spending_report.md`. The script should not be interactive and must perform all steps from data loading to final report generation.

### **Report Generation Script Requirements**

Your Python script must be structured to perform the following actions:

**1. Data Preparation**
  * Always start with: print("📊 Starting data analysis...")
  * **NOTE**: The `output/` directory has been pre-created for you. Simply save all files there.
  * Print file loading status: print(f"📂 Loading data from: {filename}")
  * Parse string dates into datetime objects.
  * Ensure transaction amounts are numeric.
  * Print data validation results
  * Validate that all transactions belong to the six existing categories: `Food & Dining`, `Merchandise & Services`, `Bills & Subscriptions`, `Travel & Transportation`, `Financial Transactions`, and `Uncategorized`. **Do not modify these categories.**

**2. Required Aggregations & Computations**
  * Print progress for each computation step
  * Total spend across all cardholders.
  * Spend by month (aggregated across all cardholders).
  * Spend by category.
  * Spend by cardholder.
  * Spend by bank.
  * Top 10 largest transactions.
  * Top 10 merchants by total spend.
  * Monthly spending trends for each individual cardholder.

**3. Required Charts**
  * **CRITICAL**: ALL charts must be saved to the `output/` directory only. Use `plt.savefig("output/chart_name.png", ...)` format.
  * **FORBIDDEN**: Do not create any directories like `/plots`, `/charts`, `/images` etc. Everything goes in `output/` only.
  * Your script must generate and save the following plots as separate PNG files in the `output/` directory.
  * Print confirmation after saving each chart
  * **Rules**: Use clear titles and labels, sort bars logically (e.g., highest to lowest), and **do not use pie charts or subplots**.
      * **Monthly Spend Trend:** Line chart of total monthly spend. Save as `output/monthly_spend_trend.png`
      * **Spend by Category:** Horizontal bar chart. Save as `output/spend_by_category.png`
      * **Spend by Cardholder:** Vertical bar chart. Save as `output/spend_by_cardholder.png`
      * **Spend by Bank:** Vertical bar chart. Save as `output/spend_by_bank.png`
      * **Top 10 Transactions:** Horizontal bar chart. Save as `output/top_10_transactions.png`
      * **Top 10 Merchants:** Vertical bar chart. Save as `output/top_10_merchants.png`
      * **Cumulative Spend Over Time:** Line chart. Save as `output/cumulative_spend.png`

**4. Markdown Report Formatting**
  * **Output Directory**: The `output/` directory is pre-created for you. Save the report as `output/spending_report.md`.
  * **Executive Summary**: The report must start with an "# Executive Summary" section that provides a high-level overview of the key findings in 3-4 bullet points before diving into detailed analysis.
  * The script will compile all analysis into a single markdown string and write it to `output/spending_report.md`.
  * **Tables and Insights**: Convert pandas DataFrames to markdown tables using `.to_markdown()`. **For every table and chart, the script must append a concise, 1-2 line summary of the key financial insight.**
  * **Embed Images**: All charts must be embedded directly into the markdown file using a Base64 data URI. **Do not use simple file links.** The script must include the helper function below to accomplish this.
  * **Confirmation Prints**: After saving any file (report or chart), your script **must** print a confirmation message to the console (e.g., `print("✅ Successfully saved file: output/spending_report.md")`). This is critical for verification.
  * Always end with: print("✅ Analysis complete!")

```python
# Helper function to be included in your script for embedding images
import base64
from pathlib import Path

def embed_image(image_path, report_content):
    try:
        print(f"🖼️ Embedding image: {image_path}")
        image_data = base64.b64encode(Path(image_path).read_bytes()).decode()
        report_content += f"![{Path(image_path).stem}](data:image/png;base64,{image_data})\\n\\n"
        print(f"✅ Successfully embedded image: {image_path}")
    except Exception as e:
        error_msg = f"*Error embedding image {image_path}: {e}*"
        print(f"⚠ {error_msg}")
        report_content += f"{error_msg}\\n\\n"
    return report_content

# --- Example Usage in your script ---
# report_content = "# Executive Summary\n\n*Key findings from the financial analysis...*\n\n## Monthly Spending\n"
# plt.savefig("output/monthly_spending.png", dpi=150, bbox_inches='tight')
# print("✅ Successfully saved file: output/monthly_spending.png")
# report_content = embed_image("output/monthly_spending.png", report_content)
# report_content += "*Insight: Spending peaks in December, reflecting holiday purchases.*\\n\\n"
```

---
## Workflow 2: Specific Questions

For specific, targeted questions, your goal is to write a Python script that directly calculates or visualizes the answer.

  * **Output Directory**: The `output/` directory is pre-created for you. Save charts as `output/chart_name.png`.
  * **FORBIDDEN**: Do not create any other directories. All files must go in the existing `output/` directory.
  * **Executive Summary**: If generating a report for broad analysis, start with an "# Executive Summary" section.
  * Always start with: print("📊 Starting data analysis...")
  * Print file loading status: print(f"📂 Loading data from: {filename}")
  * The script should print any data or calculations (e.g., using `print()` with a formatted DataFrame).
  * If a plot is necessary to answer the question, the script must save it as a PNG file in the `output/` directory. After saving the file, it **must** print a confirmation message to the console (e.g., `print("✅ Successfully saved plot: output/top_merchants.png")`).
  * **For every output (table or chart), the script must also print a concise, 1-2 line summary of the key insight.**
  * Do not generate a markdown report.
  * Always end with: print("✅ Analysis complete!")

---
## Critical Error Handling

Every Python script you write MUST include comprehensive error handling:

```python
import sys
import traceback

try:
    print("📊 Starting data analysis...")
    
    # Your main code here
    # Note: output/ directory is already created for you
    
except FileNotFoundError as e:
    print(f"⚠ File not found error: {e}")
    sys.exit(1)
except json.JSONDecodeError as e:
    print(f"⚠ JSON parsing error: {e}")
    sys.exit(1)
except Exception as e:
    print(f"⚠ Unexpected error: {e}")
    print(f"⚠ Traceback: {traceback.format_exc()}")
    sys.exit(1)
finally:
    print("✅ Analysis complete!")
```

---
## Execution Protocol

You must follow this turn-based process without deviation.

1.  **Plan:** Start by stating whether the user's request is **broad** or **specific** and briefly outline your plan.
2.  **Code:** Write all necessary Python code in a single, complete code block. Load the `combined_data.json` file at the beginning of your script.
3.  **Wait for Execution:** After providing the code block, wait for the executor_agent to run it and then provide the results (e.g., stdout, stderr, or file paths).
4.  **Handle Missing Libraries:** If the execution fails due to a missing library, provide a `bash` command to install it and then resubmit the original, unchanged Python code in the next turn.
    ```sh
    pip install pandas matplotlib seaborn numpy
    ```
5.  **Final Answer:** Once the code executes successfully and you have reviewed the output, provide a final, comprehensive explanation of the financial insights discovered. Conclude your final response with the word **STOP**. You must only provide the final answer after analyzing the actual execution results.
"""

def load_combined_data(file_path: str) -> dict:
    """Load the combined financial data JSON file."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        raise ValueError(f"Error loading combined data file: {e}")

async def run_data_analyzer(json_file_path: str, user_question: str):
    """Run the data analyzer with the given JSON file and user question."""
    
    # Validate input file exists
    if not Path(json_file_path).exists():
        raise FileNotFoundError(f"JSON file not found: {json_file_path}")
    
    # Load the data to validate it
    try:
        data = load_combined_data(json_file_path)
        print(f"✅ Data file validated: {len(data)} top-level keys found")
    except Exception as e:
        print(f"⚠ Error loading data: {e}")
        return
    
    # Create model client
    model_client = OpenAIChatCompletionClient(
        model=OPENAI_MODEL, 
        api_key=OPENAI_API_KEY
    )
    
    # Create data analyzer agent
    data_analyzer = AssistantAgent(
        name="data_analyzer", 
        model_client=model_client,
        system_message=DATA_ANALYZER_SYSTEM_MESSAGE,
        reflect_on_tool_use=True
    )
    
    # Create code executor with improved configuration
    code_executor = DockerCommandLineCodeExecutor(
        work_dir=TEMP_DIR,
        image="amancevice/pandas",  # Changed to more standard Python image
        timeout=600  # 5 minute timeout
    )
    
    try:
        await code_executor.start()
        print("✅ Docker executor started successfully")
    except Exception as e:
        print(f"⚠ Failed to start Docker executor: {e}")
        return
    
    # Create code executor agent
    executor_agent = CodeExecutorAgent(
        name="code_executor",
        code_executor=code_executor
    )
    
    # Create the team with termination conditions
    stop_termination = TextMentionTermination("STOP")
    max_message_termination = MaxMessageTermination(max_messages=30)  # Increased limit
    
    analysis_team = RoundRobinGroupChat(
        participants=[data_analyzer, executor_agent],
        termination_condition=stop_termination | max_message_termination
    )
    
    # Create/recreate output directory
    output_dir = Path(FINAL_OUTPUT_DIR)
    try:
        if output_dir.exists():
            shutil.rmtree(output_dir)
            print(f"🗑️ Removed existing output directory")
        output_dir.mkdir(parents=True, exist_ok=True)
        print(f"📁 Created fresh output directory: {output_dir}")
    except Exception as e:
        print(f"⚠ Failed to create output directory: {e}")
        return
    
    # Copy the JSON file to ensure it's accessible in the Docker container
    try:
        # Read and write to ensure the file is in the working directory
        with open(json_file_path, 'r') as src:
            data_content = src.read()
        with open('./combined_data.json', 'w') as dst:
            dst.write(data_content)
        print(f"✅ Copied data file to working directory: ./combined_data.json")
    except Exception as e:
        print(f"⚠ Failed to copy data file: {e}")
        return
    
    # Prepare the initial task message
    initial_message = f"""
I have a combined financial data JSON file at: ./combined_data.json
User Question: {user_question}

Please analyze this financial data and provide insights based on the question asked.

IMPORTANT: Your Python script must include extensive print statements to show progress and results.
Start every script with: print("📊 Starting data analysis...")
End every script with: print("✅ Analysis complete!")
"""
    
    task = TextMessage(
        content=initial_message,
        source="user"
    )
    
    # Print a clean, consolidated header
    print("=" * 60)
    print("🚀 FINANCIAL DATA ANALYSIS STARTING 🚀")
    print(f"   - Question: {user_question}")
    print(f"   - Data Source: {json_file_path}")
    print(f"   - Model: {OPENAI_MODEL}")
    print("=" * 60)
    
    # Run the analysis
    result = None
    try:
        result = await Console(analysis_team.run_stream(task=task))
        
        # Print a clean, results-focused summary
        print("\n" + "=" * 60)
        print("✅ ANALYSIS COMPLETE")
        print("=" * 60)

        # Check for generated artifacts
        report_files = list(Path(FINAL_OUTPUT_DIR).glob("*report*.md")) if Path(FINAL_OUTPUT_DIR).exists() else []
        plot_files = list(Path(FINAL_OUTPUT_DIR).glob("*.png")) if Path(FINAL_OUTPUT_DIR).exists() else []

        if report_files:
            print(f"📊 BROAD ANALYSIS: Report generated successfully.")
            for report in report_files:
                print(f"   - Report: {report.name} ({report.stat().st_size / 1024:.2f} KB)")
        
        if plot_files:
            print(f"📈 CHARTS: {len(plot_files)} plot(s) created.")
            for plot in plot_files:
                print(f"   - Chart: {plot.name}")

        if not report_files and not plot_files and result.messages:
             print("🎯 SPECIFIC ANALYSIS: Direct answer provided in the conversation above.")

        # Check for termination condition
        if result and hasattr(result, 'messages') and result.messages:
            last_message = result.messages[-1]
            if hasattr(last_message, 'content') and "STOP" in str(last_message.content):
                print("\nOutcome: Analysis finished with STOP keyword.")
            else:
                print("\nOutcome: Analysis ended (likely due to message limit).")

    except Exception as e:
        print(f"⚠ An error occurred during analysis: {e}")
        import traceback
        print(f"Full traceback: {traceback.format_exc()}")
        
        # Print last few messages for debugging if available
        if result and hasattr(result, 'messages') and result.messages:
            print("\nLast message content preview for debugging:")
            for msg in result.messages[-3:]:
                content_preview = str(getattr(msg, 'content', ''))[:200] + "..."
                print(f"  {getattr(msg, 'source', 'unknown')}: {content_preview}")
    finally:
        # Clean up
        try:
            await code_executor.stop()
            print("✅ Docker executor stopped successfully")
        except Exception as e:
            print(f"⚠️ Warning during cleanup: {e}")
        print("\n🏁 Analysis session ended.")

# ============================================================================
# MAIN PIPELINE ORCHESTRATOR
# ============================================================================

async def run_complete_pipeline(input_pdf_dir: str, user_question: str):
    """
    Run the complete pipeline:
    1. Convert PDFs to text files
    2. Parse bank statements to JSON
    3. Generate reports based on user question
    """
    
    print("=" * 80)
    print("🏦 FINANCIAL STATEMENT PROCESSING PIPELINE")
    print("=" * 80)
    print(f"📁 Input Directory: {input_pdf_dir}")
    print(f"❓ User Question: {user_question}")
    print("=" * 80)
    
    # STEP 1: Convert PDFs to text files
    print("\n🔄 STEP 1: Converting PDFs to text files...")
    print("-" * 50)
    
    text_files = convert_pdfs_in_dir(input_pdf_dir, TEMP_DIR)
    
    if not text_files:
        print("❌ No PDF files were successfully converted. Pipeline stopped.")
        return
    
    print(f"✅ Successfully converted {len(text_files)} PDF files to text")
    for file in text_files:
        print(f"   - {file}")
    
    # STEP 2: Parse bank statements to JSON
    print("\n🔄 STEP 2: Parsing bank statements...")
    print("-" * 50)
    
    parsed_data = await run_parsing_agent(text_files)
    
    if not parsed_data:
        print("❌ No bank statements were successfully parsed. Pipeline stopped.")
        return
    
    # Save the combined JSON data
    combined_json_path = COMBINED_JSON_FILE
    with open(combined_json_path, "w", encoding="utf-8") as f:
        json.dump(parsed_data, f, indent=2, ensure_ascii=False)
    
    print(f"✅ Successfully parsed and combined bank statements")
    print(f"   - Combined data saved to: {combined_json_path}")
    print(f"   - Total files processed: {parsed_data.get('combined_summary', {}).get('total_files_processed', 0)}")
    print(f"   - Total transactions: {parsed_data.get('combined_summary', {}).get('total_transactions', 0)}")
    
    # STEP 3: Generate reports based on user question
    print("\n🔄 STEP 3: Analyzing data and generating insights...")
    print("-" * 50)
    
    await run_data_analyzer(combined_json_path, user_question)
    
    print("\n" + "=" * 80)
    print("🎉 PIPELINE COMPLETE!")
    print("=" * 80)
    print("📋 SUMMARY:")
    print(f"   - PDFs processed: {len(text_files)}")
    print(f"   - Statements parsed: {parsed_data.get('combined_summary', {}).get('total_files_processed', 0)}")
    print(f"   - Total transactions: {parsed_data.get('combined_summary', {}).get('total_transactions', 0)}")
    print(f"   - Combined data: {combined_json_path}")
    
    # Check final output
    final_output_path = Path(FINAL_OUTPUT_DIR)
    if final_output_path.exists():
        reports = list(final_output_path.glob("*.md"))
        charts = list(final_output_path.glob("*.png"))
        if reports or charts:
            print(f"   - Analysis output: {final_output_path}/")
            if reports:
                print(f"     • {len(reports)} report(s)")
            if charts:
                print(f"     • {len(charts)} chart(s)")
    
    print("=" * 80)

def main():
    """Main function to handle command line arguments and run the pipeline."""
    global TEMP_DIR, FINAL_OUTPUT_DIR, OUTPUT_DIR
    parser = argparse.ArgumentParser(
        description="Complete Financial Statement Processing Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python financial_processor.py --input-dir /path/to/pdfs --question "Analyze spending patterns"
  python financial_processor.py --input-dir ./statements --question "What is total spending on Food & Dining?"
  python financial_processor.py --input-dir ./bank_pdfs --question "Who spent the most money?"
        """
    )
    
    parser.add_argument(
        "--input-dir", 
        required=True,
        help="Path to the directory containing PDF bank statements"
    )
    parser.add_argument(
        "--question",
        required=True,
        help="Question to ask about the financial data (use quotes for multi-word questions)"
    )
    parser.add_argument(
        "--temp-dir",
        default=TEMP_DIR,
        help=f"Temporary directory for intermediate files (default: {TEMP_DIR})"
    )
    parser.add_argument(
        "--output-dir",
        default=FINAL_OUTPUT_DIR,
        help=f"Output directory for final reports and charts (default: {FINAL_OUTPUT_DIR})"
    )
    
    args = parser.parse_args()
    
    # Update global directories if specified
    # Update global directories if specified
    # global TEMP_DIR, FINAL_OUTPUT_DIR, OUTPUT_DIR
    TEMP_DIR = args.temp_dir
    FINAL_OUTPUT_DIR = args.output_dir
    OUTPUT_DIR = f"{TEMP_DIR}/parsed_statements"  # Update OUTPUT_DIR based on TEMP_DIR
    
    # Validate input directory
    if not Path(args.input_dir).exists():
        print(f"❌ Error: Input directory not found: {args.input_dir}")
        return
    
    if not Path(args.input_dir).is_dir():
        print(f"❌ Error: Input path is not a directory: {args.input_dir}")
        return
    
    # Check for required environment variables
    missing_vars = []
    if not ANTHROPIC_API_KEY:
        missing_vars.append("ANTHROPIC_API_KEY")
    if not OPENAI_API_KEY:
        missing_vars.append("OPENAI_API_KEY2")
    
    if missing_vars:
        print(f"❌ Error: Missing required environment variables: {', '.join(missing_vars)}")
        print("Please set these in your .env file or environment.")
        return
    
    print("🔍 Configuration validated:")
    print(f"   - Input directory: {args.input_dir}")
    print(f"   - Question: {args.question}")
    print(f"   - Temp directory: {TEMP_DIR}")
    print(f"   - Output directory: {FINAL_OUTPUT_DIR}")
    print(f"   - Anthropic model: {ANTHROPIC_MODEL}")
    print(f"   - OpenAI model: {OPENAI_MODEL}")
    
    # Run the complete pipeline
    try:
        asyncio.run(run_complete_pipeline(args.input_dir, args.question))
    except KeyboardInterrupt:
        print("\n⚠️ Pipeline interrupted by user")
    except Exception as e:
        print(f"❌ Fatal error: {e}")
        print(f"Full traceback: {traceback.format_exc()}")

if __name__ == "__main__":
    main()
#!/usr/bin/env python3
import os
import asyncio
import json
import re
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
BANK_STATEMENT_FILE = "temp/statement.txt"  # Text file containing raw statement
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")  # Default model
# ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-3-5-haiku-latest")  # Default model
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")  # Must be set in your .env

if not ANTHROPIC_API_KEY:
    raise EnvironmentError("Please set the ANTHROPIC_API_KEY environment variable.")

# === Helper to read statement text ===
def load_statement(file_path: str) -> str:
    with open(file_path, "r", encoding="utf-8") as f:
        return f.read()

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

async def run_parsing_agent():
    statement_text = load_statement(BANK_STATEMENT_FILE)

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
    # Using custom termination condition that stops when valid JSON is found
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

    print("Stage 1: Parsing statement...")
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
        raise ValueError("Failed to parse statement in Stage 1")

    print("Stage 1 completed successfully. JSON extracted.")

    # STAGE 2: Categorizer processes the parsed JSON
    categorizer_task = TextMessage(
        content=f"Here is the parsed JSON to categorize:\n```json\n{json.dumps(parsed_json, indent=2)}\n```",
        source="user"
    )

    # Using custom termination condition that stops when categorized JSON is found
    categorization_termination = CategorizationSuccessTermination()
    categorizer_team = RoundRobinGroupChat(
        participants=[categorizer_agent],
        termination_condition=categorization_termination
    )

    print("Stage 2: Categorizing transactions...")
    categorization_result = await Console(categorizer_team.run_stream(task=categorizer_task))

    # Stop executor safely
    await code_executor.stop()

    # Search categorization result for final JSON
    final_parsed_json = None

    # 1) prefer categorizer messages
    for msg in categorization_result.messages:
        src = getattr(msg, "source", "")
        content = getattr(msg, "content", None)
        # normalize content to string for searching
        try:
            content_str = content if isinstance(content, str) else str(content)
        except Exception:
            content_str = None

        if not content_str:
            continue

        if src == "categorizer":
            final_parsed_json = extract_json_from_text(content_str)
            if final_parsed_json is not None:
                return final_parsed_json

    # 2) fallback: check all messages in categorization result
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
            return final_parsed_json

    # 3) If still not found — print helpful debug info and return the parsed JSON from stage 1
    print("\n[DEBUG] No categorized JSON detected. Using Stage 1 result:")
    for idx, msg in enumerate(categorization_result.messages):
        src = getattr(msg, "source", "<no-source>")
        content = getattr(msg, "content", "")
        try:
            preview = (content if isinstance(content, str) else str(content))[:800]
        except Exception:
            preview = "<could not stringify content>"
        print(f"Message[{idx}] source={src} preview={preview!r}\n{'-'*40}")

    # Return the original parsed JSON from stage 1 as fallback
    return parsed_json


if __name__ == "__main__":
    parsed_data = asyncio.run(run_parsing_agent())
    print("\n=== Final Parsed JSON Object ===")
    print(json.dumps(parsed_data, indent=2, ensure_ascii=False))

    # Save the JSON to a file
    output_filename = "parsed_data.json"
    with open(output_filename, "w", encoding="utf-8") as f:
        json.dump(parsed_data, f, indent=2, ensure_ascii=False)
    
    print(f"\nJSON data saved to {output_filename}")
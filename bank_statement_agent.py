# #!/usr/bin/env python3
#!/usr/bin/env python3
import os
import asyncio
import json
import re
from autogen_ext.models.openai import OpenAIChatCompletionClient
from autogen_agentchat.agents import AssistantAgent, CodeExecutorAgent
from autogen_agentchat.teams import RoundRobinGroupChat
from autogen_agentchat.conditions import MaxMessageTermination
from autogen_agentchat.messages import TextMessage
from autogen_ext.code_executors.local import LocalCommandLineCodeExecutor
from autogen_ext.code_executors.docker import DockerCommandLineCodeExecutor
from autogen_agentchat.ui import Console
from dotenv import load_dotenv

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
            "statement text stored in a variable named `statement_text`. Write a single "
            "```python``` code block that:\n"
            "1. Parses `statement_text` into a JSON object with keys:\n"
            "   - 'transactions_by_cardholder': a dictionary where each key is a cardholder name "
            "     and the value is a list of {sale_date, post_date, description, amount}.\n"
            "   - 'summary': contains 'bank_name', 'total_transactions','total_amount','previous_balance','payments','credits','purchases','cash_advances','fees','interest','new_balance', rewards_balance, 'available_credit_limit'.\n"
            "2. Ensure amounts are numbers (floats) and NOT zero.\n"
            "3. Ensure transactions for all cardholders are captured correctly. It is very rare to have no transactions for a cardholder if there are multiple card holders.\n"
            "4. Prints **only** the JSON via `print(json.dumps(parsed, ensure_ascii=False))`.\n"
            "Do not output any explanation or extra text."
        ),
        reflect_on_tool_use=True
    )

    # Local executor for running the code
    # code_executor = LocalCommandLineCodeExecutor(work_dir="agent_exec_workspace")
    code_executor = DockerCommandLineCodeExecutor(work_dir="temp")
    await code_executor.start()

    # Code execution agent
    executor_agent = CodeExecutorAgent(
        name="executor",
        code_executor=code_executor
    )

    # --- NEW: Categorizer Agent ---
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
    "Uncategorized: For any transaction that does not clearly fit into the categories above.\n"
    ),
        reflect_on_tool_use=False
    )


    # Round-robin chat between assistant and executor
    team = RoundRobinGroupChat(
        participants=[assistant, executor_agent, categorizer_agent],
        termination_condition=MaxMessageTermination(30)
    )

    # Send the statement as initial task
    task = TextMessage(
        content=f"statement = '''{statement_text}'''",
        source="user"
    )

    result = await Console(team.run_stream(task=task))
    # result = await team.run(task=task)
    # result = team.run_stream(task=task)
    # async for message in result:
    #     print(message)

    # Stop executor safely
    await code_executor.stop()

        # ----------------------------
    # Robust JSON extraction logic
    # ----------------------------
      # make sure this import is available (or add at top of file)

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

    # Search all messages for JSON (executor first, then assistant, then any)
    parsed_json = None

    # 1) prefer executor messages (they are expected to print JSON)
    for msg in result.messages:
        src = getattr(msg, "source", "")
        content = getattr(msg, "content", None)
        # normalize content to string for searching
        try:
            content_str = content if isinstance(content, str) else str(content)
        except Exception:
            content_str = None

        if not content_str:
            continue

        # direct JSON candidate in executor output or fenced block
        if src == "categorizer":
            parsed_json = extract_json_from_text(content_str)
            if parsed_json is not None:
                return parsed_json

        elif src == "executor":
            parsed_json = extract_json_from_text(content_str)
            if parsed_json is not None:
                return parsed_json

    # 2) fallback: check assistant / all messages
    for msg in result.messages:
        content = getattr(msg, "content", None)
        try:
            content_str = content if isinstance(content, str) else str(content)
        except Exception:
            content_str = None
        if not content_str:
            continue
        parsed_json = extract_json_from_text(content_str)
        if parsed_json is not None:
            return parsed_json

    # 3) If still not found — print helpful debug info and return empty dict
    print("\n[DEBUG] No JSON detected. Conversation summary (truncated):")
    for idx, msg in enumerate(result.messages):
        src = getattr(msg, "source", "<no-source>")
        content = getattr(msg, "content", "")
        # attempt safe string conversion
        try:
            preview = (content if isinstance(content, str) else str(content))[:800]
        except Exception:
            preview = "<could not stringify content>"
        print(f"Message[{idx}] source={src} preview={preview!r}\n{'-'*40}")

    # Return empty dict instead of raising, so caller can handle fallback
    return {}


    # # Extract and return JSON object from executor's output
    # for msg in result.messages:
    #     if getattr(msg, "source", "") == "executor":
    #         content = getattr(msg, "content", "")
    #         if isinstance(content, str) and content.strip().startswith("{"):
    #             parsed_json = json.loads(content.strip())
    #             return parsed_json  # Return as dict for reuse

    # raise ValueError("No JSON output detected from executor.")

if __name__ == "__main__":
    parsed_data = asyncio.run(run_parsing_agent())
    print("\n=== Parsed JSON Object ===")
    print(json.dumps(parsed_data, indent=2, ensure_ascii=False))

    # Save the JSON to a file
    output_filename = "parsed_data.json"
    with open(output_filename, "w", encoding="utf-8") as f:
        json.dump(parsed_data, f, indent=2, ensure_ascii=False)
    
    print(f"\nJSON data saved to {output_filename}")
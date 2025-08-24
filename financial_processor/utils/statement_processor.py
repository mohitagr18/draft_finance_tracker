"""Enhanced single statement processing with improved agent interaction."""

import json
import os
from pathlib import Path
from typing import Tuple

from autogen_agentchat.agents import AssistantAgent, CodeExecutorAgent
from autogen_agentchat.teams import RoundRobinGroupChat
from autogen_agentchat.conditions import MaxMessageTermination
from autogen_agentchat.messages import TextMessage
from autogen_ext.code_executors.docker import DockerCommandLineCodeExecutor
from autogen_agentchat.ui import Console

from config.models import get_anthropic_client, get_openai_client
from utils.file_utils import load_statement
from utils.json_utils import extract_json_from_text
from utils.quality_checks import quality_gate
from utils.termination_conditions import JSONSuccessTermination, CategorizationSuccessTermination
from agents.prompts.statement_parser_message import STATEMENT_PARSER_SYSTEM_MESSAGE
from agents.prompts.categorizer_message import CATEGORIZER_SYSTEM_MESSAGE
from agents.prompts.task_message import TASK_MESSAGE
from config.constants import TEMP_DIR


async def process_single_statement(file_path: str, output_dir: str, retry_level: int = 0) -> Tuple[bool, str, dict]:
    """
    Enhanced statement processing with better agent interaction.
    """
    try:
        statement_text = load_statement(file_path)
        work_dir = TEMP_DIR
        os.makedirs(work_dir, exist_ok=True)
        
        # Write statement to file
        input_fp = Path(work_dir) / "statement.txt"
        with open(input_fp, "w", encoding="utf-8") as f:
            f.write(statement_text)

        model_client = get_openai_client()

        # Enhanced assistant with more detailed feedback instructions
        enhanced_system_message = STATEMENT_PARSER_SYSTEM_MESSAGE + """

CRITICAL: You MUST analyze executor feedback and improve your code iteratively.

EXECUTOR FEEDBACK ANALYSIS:
- If executor shows empty/few transactions: Your parsing patterns are wrong
- If executor shows wrong cardholders: Your name extraction logic failed  
- If executor shows "No valid transactions": Your date/amount parsing is incorrect
- If executor shows errors: Fix the syntax and retry

DEBUGGING STRATEGY:
1. First attempt: Write code with extensive debug prints to understand the data structure
2. Based on executor output: Identify what's wrong and fix specific issues
3. Continue iterating until you get good results

SAMPLE DEBUG CODE STRUCTURE:
```python
# Read and examine the raw text first
with open('statement.txt', 'r', encoding='utf-8') as f:
    text = f.read()

print("=== RAW TEXT SAMPLE ===")
print(text[:2000])  # Show first 2000 chars
print("=== END SAMPLE ===")

# Look for cardholder patterns
import re
print("\\n=== CARDHOLDER SEARCH ===")
# Try multiple patterns and print what you find
patterns = [
    r'([A-Z]+\\s+[A-Z]+)\\s*\\n.*?(?:Card ending|Account ending)',
    r'([A-Z]+\\s+[A-Z]+)\\s*#\\d+:\\s*Transactions',
    r'CARDHOLDER SUMMARY.*?\\n\\s*([A-Z]+\\s+[A-Z]+)'
]

for i, pattern in enumerate(patterns):
    matches = re.findall(pattern, text, re.IGNORECASE | re.DOTALL)
    print(f"Pattern {i}: {matches}")

# Look for transaction patterns  
print("\\n=== TRANSACTION SEARCH ===")
tx_patterns = [
    r'\\d{1,2}/\\d{1,2}\\s+\\d{1,2}/\\d{1,2}\\s+.*?\\$[\\d,]+\\.\\d{2}',
    r'[A-Z][a-z]{2}\\s+\\d{1,2}\\s+[A-Z][a-z]{2}\\s+\\d{1,2}\\s+.*?\\$[\\d,]+\\.\\d{2}',
    r'[A-Z][a-z]{2}\\s+\\d{1,2}\\s+.*?\\$[\\d,]+\\.\\d{2}'
]

for i, pattern in enumerate(tx_patterns):
    matches = re.findall(pattern, text)
    print(f"TX Pattern {i}: Found {len(matches)} matches")
    if matches:
        print(f"  Sample: {matches[0]}")

# Then implement actual parsing based on what you discovered
```

ALWAYS respond to executor feedback with improved code. Don't repeat the same approach if it failed.
"""

        assistant = AssistantAgent(
            name="assistant",
            model_client=model_client,
            system_message=enhanced_system_message,
            reflect_on_tool_use=True
        )

        # Code executor setup
        code_executor = DockerCommandLineCodeExecutor(
            work_dir=TEMP_DIR,
            image="amancevice/pandas"
        )
        await code_executor.start()

        executor_agent = CodeExecutorAgent(
            name="executor",
            code_executor=code_executor
        )

        # Enhanced task message with more specific instructions
        enhanced_task = TextMessage(
            content=f"""
You need to parse the bank statement in 'statement.txt'. 

IMPORTANT CONTEXT:
- This is retry level {retry_level} (0=strict, 1=normal, 2=relaxed quality requirements)
- The statement may be from Citi, Capital One, or other banks
- Different banks have different transaction formats

STEP-BY-STEP APPROACH:
1. First, write exploratory code to understand the text structure
2. Identify cardholder patterns and transaction formats
3. Write parsing code based on what you discovered
4. If I give you feedback about failures, analyze and improve your approach

Start by examining the raw text structure and identifying patterns.
""",
            source="user"
        )

        # Use standard termination with more messages allowed
        json_termination = JSONSuccessTermination()
        max_termination = MaxMessageTermination(max_messages=12)  # Allow more messages
        
        parsing_team = RoundRobinGroupChat(
            participants=[assistant, executor_agent],
            termination_condition=json_termination | max_termination
        )

        print(f"\n🚀 Starting parsing conversation (retry_level={retry_level})")
        parsing_result = await Console(parsing_team.run_stream(task=enhanced_task))

        # Enhanced debugging
        print(f"\n=== CONVERSATION ANALYSIS ===")
        print(f"Total messages: {len(parsing_result.messages)}")
        
        assistant_messages = [m for m in parsing_result.messages if getattr(m, "source", "") == "assistant"]
        executor_messages = [m for m in parsing_result.messages if getattr(m, "source", "") == "executor"]
        
        print(f"Assistant messages: {len(assistant_messages)}")
        print(f"Executor messages: {len(executor_messages)}")
        
        # Check for iterative improvement
        if len(assistant_messages) > 1:
            print("✅ Multiple assistant messages found - iteration occurred")
        else:
            print("⚠️ Only one assistant message - no iteration detected")

        # Extract best JSON result
        best_json = None
        best_quality_score = -1
        
        for msg in parsing_result.messages:
            if getattr(msg, "source", "") == "executor":
                content = getattr(msg, "content", "")
                parsed_json = extract_json_from_text(content)
                
                if parsed_json:
                    # Score based on transaction count and cardholder count
                    tx_map = parsed_json.get("transactions_by_cardholder", {})
                    total_tx = sum(len(txs) for txs in tx_map.values() if isinstance(txs, list))
                    cardholder_count = len(tx_map)
                    
                    quality_score = total_tx + (cardholder_count * 10)  # Favor more cardholders
                    
                    print(f"📊 Found JSON with {cardholder_count} cardholders, {total_tx} transactions (score: {quality_score})")
                    
                    if quality_score > best_quality_score:
                        best_quality_score = quality_score
                        best_json = parsed_json

        if not best_json:
            await code_executor.stop()
            return False, "No valid JSON found after enhanced conversation", {}

        # Apply quality gate to the best result
        ok, msg_text, cleaned_json = quality_gate(statement_text, best_json, retry_level=retry_level)
        
        if not ok:
            await code_executor.stop()
            return False, f"Quality gate failed: {msg_text}", {}

        # Stage 2: Categorization (unchanged)
        categorizer_agent = AssistantAgent(
            name="categorizer",
            model_client=model_client,
            system_message=CATEGORIZER_SYSTEM_MESSAGE,
            reflect_on_tool_use=False
        )

        categorizer_task = TextMessage(
            content=f"Here is the parsed JSON to categorize:\n```json\n{json.dumps(cleaned_json, indent=2)}\n```",
            source="user"
        )

        categorization_termination = CategorizationSuccessTermination()
        max_message_termination = MaxMessageTermination(max_messages=5)
        
        categorizer_team = RoundRobinGroupChat(
            participants=[categorizer_agent],
            termination_condition=categorization_termination | max_message_termination
        )

        categorization_result = await Console(categorizer_team.run_stream(task=categorizer_task))

        # Extract final categorized result
        final_json = cleaned_json  # Default fallback
        
        for msg in categorization_result.messages:
            if getattr(msg, "source", "") == "categorizer":
                content = getattr(msg, "content", "")
                categorized = extract_json_from_text(content)
                if categorized:
                    final_json = categorized
                    break

        await code_executor.stop()

        # Save result
        filename = Path(file_path).stem
        individual_output_path = Path(output_dir) / f"{filename}_parsed.json"
        with open(individual_output_path, "w", encoding="utf-8") as f:
            json.dump(final_json, f, indent=2, ensure_ascii=False)

        return True, "", final_json

    except Exception as e:
        return False, str(e), {}
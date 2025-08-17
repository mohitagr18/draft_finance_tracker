#!/usr/bin/env python3
import os
import asyncio
import json
import argparse
from pathlib import Path
from autogen_ext.models.anthropic import AnthropicChatCompletionClient
from autogen_ext.models.openai import OpenAIChatCompletionClient
from autogen_agentchat.agents import AssistantAgent, CodeExecutorAgent
from autogen_agentchat.teams import RoundRobinGroupChat
from autogen_agentchat.conditions import TextMentionTermination, MaxMessageTermination
from autogen_agentchat.messages import TextMessage
from autogen_ext.code_executors.docker import DockerCommandLineCodeExecutor
from autogen_agentchat.ui import Console
from dotenv import load_dotenv

load_dotenv()


# === CONFIGURATION ===
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")  # Fixed typo: was "gpt-4.1-mini"
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY2") 

if not OPENAI_API_KEY:
    raise EnvironmentError("Please set the OPENAI_API_KEY2 environment variable.")

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
- Every script must start with: print("🔄 Starting data analysis...")
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
  * Always start with: print("🔄 Starting data analysis...")
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
  * Your script must generate and save the following plots as separate PNG files.
  * Print confirmation after saving each chart
  * **Rules**: Use clear titles and labels, sort bars logically (e.g., highest to lowest), and **do not use pie charts or subplots**.
      * **Monthly Spend Trend:** Line chart of total monthly spend.
      * **Spend by Category:** Horizontal bar chart.
      * **Spend by Cardholder:** Vertical bar chart.
      * **Spend by Bank:** Vertical bar chart.
      * **Top 10 Transactions:** Horizontal bar chart.
      * **Top 10 Merchants:** Vertical bar chart.
      * **Cumulative Spend Over Time:** Line chart.

**4. Markdown Report Formatting**
  * The script will compile all analysis into a single markdown string and write it to `spending_report.md`.
  * **Tables and Insights**: Convert pandas DataFrames to markdown tables using `.to_markdown()`. **For every table and chart, the script must append a concise, 1-2 line summary of the key financial insight.**
  * **Embed Images**: All charts must be embedded directly into the markdown file using a Base64 data URI. **Do not use simple file links.** The script must include the helper function below to accomplish this.
  * **Confirmation Prints**: After saving any file (report or chart), your script **must** print a confirmation message to the console (e.g., `print("✅ Successfully saved file: spending_report.md")`). This is critical for verification.
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
        print(f"❌ {error_msg}")
        report_content += f"{error_msg}\\n\\n"
    return report_content

# --- Example Usage in your script ---
# report_content = "## Monthly Spending\n"
# plt.savefig("monthly_spending.png", dpi=150, bbox_inches='tight')
# print("✅ Successfully saved file: monthly_spending.png")
# report_content = embed_image("monthly_spending.png", report_content)
# report_content += "*Insight: Spending peaks in December, reflecting holiday purchases.*\\n\\n"
```

---
## Workflow 2: Specific Questions

For specific, targeted questions, your goal is to write a Python script that directly calculates or visualizes the answer.

  * Always start with: print("🔄 Starting data analysis...")
  * Print file loading status: print(f"📂 Loading data from: {filename}")
  * The script should print any data or calculations (e.g., using `print()` with a formatted DataFrame).
  * If a plot is necessary to answer the question, the script must save it as a PNG file. After saving the file, it **must** print a confirmation message to the console (e.g., `print("✅ Successfully saved plot: top_merchants.png")`).
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
    print("🔄 Starting data analysis...")
    
    # Your main code here
    
except FileNotFoundError as e:
    print(f"❌ File not found error: {e}")
    sys.exit(1)
except json.JSONDecodeError as e:
    print(f"❌ JSON parsing error: {e}")
    sys.exit(1)
except Exception as e:
    print(f"❌ Unexpected error: {e}")
    print(f"❌ Traceback: {traceback.format_exc()}")
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
        print(f"❌ Error loading data: {e}")
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
        work_dir=".",
        image="amancevice/pandas",  # Changed to more standard Python image
        timeout=300  # 5 minute timeout
    )
    
    try:
        await code_executor.start()
        print("✅ Docker executor started successfully")
    except Exception as e:
        print(f"❌ Failed to start Docker executor: {e}")
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
    
    # Copy the JSON file to ensure it's accessible in the Docker container
    try:
        # Read and write to ensure the file is in the working directory
        with open(json_file_path, 'r') as src:
            data_content = src.read()
        with open('./combined_data.json', 'w') as dst:
            dst.write(data_content)
        print(f"✅ Copied data file to working directory: ./combined_data.json")
    except Exception as e:
        print(f"❌ Failed to copy data file: {e}")
        return
    
    # Prepare the initial task message
    initial_message = f"""
I have a combined financial data JSON file at: ./combined_data.json
User Question: {user_question}

Please analyze this financial data and provide insights based on the question asked.

IMPORTANT: Your Python script must include extensive print statements to show progress and results.
Start every script with: print("🔄 Starting data analysis...")
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
        report_files = list(Path(".").glob("*report*.md"))
        plot_files = list(Path(".").glob("*.png"))

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
        print(f"❌ An error occurred during analysis: {e}")
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

def main():
    parser = argparse.ArgumentParser(description="Financial Data Analyzer")
    parser.add_argument(
        "json_file", 
        help="Path to the combined financial data JSON file (e.g., combined_parsed_data.json)"
    )
    parser.add_argument(
        "question",
        help="Question to ask about the financial data (use quotes for multi-word questions)"
    )
    
    args = parser.parse_args()
    
    # Validate arguments
    if not Path(args.json_file).exists():
        print(f"❌ Error: JSON file not found: {args.json_file}")
        return
    
    print(f"🔍 Analyzing: {args.json_file}")
    print(f"❓ Question: {args.question}")
    
    # Run the analyzer
    try:
        asyncio.run(run_data_analyzer(args.json_file, args.question))
    except KeyboardInterrupt:
        print("\n⚠️ Analysis interrupted by user")
    except Exception as e:
        print(f"❌ Fatal error: {e}")
        import traceback
        print(f"Full traceback: {traceback.format_exc()}")

if __name__ == "__main__":
    main()
#!/usr/bin/env python3
import os
import asyncio
import json
import argparse
from pathlib import Path
from autogen_ext.models.anthropic import AnthropicChatCompletionClient
from autogen_agentchat.agents import AssistantAgent, CodeExecutorAgent
from autogen_agentchat.teams import RoundRobinGroupChat
from autogen_agentchat.conditions import TextMentionTermination
from autogen_agentchat.messages import TextMessage
from autogen_ext.code_executors.docker import DockerCommandLineCodeExecutor
from autogen_agentchat.ui import Console
from dotenv import load_dotenv

load_dotenv()

# === CONFIGURATION ===
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

if not ANTHROPIC_API_KEY:
    raise EnvironmentError("Please set the ANTHROPIC_API_KEY environment variable.")

# Data Analyzer System Message
DATA_ANALYZER_SYSTEM_MESSAGE = """
You are a data analyst agent with expertise in financial data analysis, Python, and working with JSON/CSV data. 
You will receive a file named `combined_data.json` which contains parsed and categorized bank statement data with the following structure:

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
  "summary_by_bank": {
    "bank_name": {
      "total_statements": 2,
      "total_transactions": 45,
      "total_amount": 2500.00,
      "cardholders": ["John Doe", "Jane Doe"]
    }
  },
  "summary_by_cardholder": {
    "cardholder_name": {
      "total_transactions": 25,
      "total_amount": 1500.00,
      "banks": {},
      "category_totals": {}
    }
  },
  "category_totals": {
    "Food & Dining": 890.00
  }
}
```

Your **first and most important step** is to determine if the user's request is **specific** or **broad**.

* A **specific question** has a clear, narrow goal.
    * *Examples: "What is the total spending on Food & Dining?", "Who spent the most money?", "Show me spending by month for John Doe", "What are the top 5 merchants by spending?"*
* A **broad question** is open-ended and asks for general exploration.
    * *Examples: "Analyze the spending data," "Give me insights on spending patterns," "Create a comprehensive spending report."*

Based on this, you will follow one of two workflows.

---

### Workflow 1: Broad Questions

If the request is **broad**, your goal is to perform a comprehensive financial spending analysis 
and generate a single, detailed, and web-friendly markdown report named `spending_report.md`.

Follow this standardized report format:

1. **Data Preparation**
- Parse dates correctly (convert string dates to datetime).
- Ensure amounts are numeric.
- Validate that all transactions have the six standard categories:
    - Food & Dining
    - Merchandise & Services  
    - Bills & Subscriptions
    - Travel & Transportation
    - Financial Transactions
    - Uncategorized

2. **Key Aggregations to compute**
- Total spend across all cardholders and statements.
- Spend by month (aggregated across all cardholders).
- Spend by category (total across entire dataset).
- Spend by cardholder.
- Spend by bank.
- Top 10 largest individual transactions.
- Top 10 merchants by total spend amount.
- Monthly spending trends for each cardholder.

3. **Charts to include** (each chart in a separate figure; no subplots; no pie charts):
- Monthly Spend Trend – Line chart of total monthly spend across all cardholders.
- Spend by Category – Horizontal bar chart of total spend per category.
- Spend by Cardholder – Vertical bar chart of total spend per cardholder.
- Spend by Bank – Vertical bar chart of total spend per bank.
- Top 10 Transactions – Horizontal bar chart of the largest transactions.
- Top 10 Merchants by Spend – Vertical bar chart of the highest-spending merchants.
- Cumulative Spend Over Time – Line chart of cumulative spend across the dataset's date range.

4. **Report layout**
- Title: "Financial Spending Analysis Report".
- Date range covered by the data.
- Executive Summary with KPI table (Total Spend, Number of Cardholders, Number of Banks, Average Monthly Spend, Highest Category Spend).
- Charts in the order listed above.
- Detailed tables: Top 10 Transactions, Top 10 Merchants, Monthly Spending Breakdown.

**DO's**

✅ Always use the existing six category classifications from the data.

✅ Label axes, titles, and gridlines clearly.

✅ Sort bars logically (highest to lowest for spending amounts).

✅ Use consistent date formatting (YYYY-MM for monthly aggregations).

✅ Handle missing or inconsistent data gracefully.

✅ Include insights and observations for every chart and table.

**DON'Ts**

❌ No pie charts.

❌ No subplots.

❌ No mixing of chart types in the same figure.

❌ Don't modify the existing category classifications.

Your Python code for this workflow must generate this report with the following rules:

* **Format Tables and Add Insights Correctly:** When including DataFrame outputs, 
you **must** convert the DataFrame to a markdown string using the `.to_markdown()` method and 
then add your analytical insight.
    ```python
    # Example for formatting a pandas DataFrame
    stats_df = df.describe()
    report_content += stats_df.to_markdown()
    report_content += "\\n\\n*Insight: The average transaction amount is $45.20, with significant variation indicating both small daily purchases and larger periodic expenses.*\\n\\n"
    ```

* **Embed Images for Web and Add Insights:** You **must** embed plots directly into the markdown file. 
Do not use simple file links. Use a helper function to read the image, convert it to a Base64 string, 
and create a data URI. You **must** follow each image with an insight.
    ```python
    # Use this helper function to embed images
    import base64
    from pathlib import Path

    def embed_image(image_path):
        try:
            image_data = base64.b64encode(Path(image_path).read_bytes()).decode()
            return f"![{Path(image_path).stem}](data:image/png;base64,{image_data})"
        except Exception as e:
            return f"Error embedding image {image_path}: {e}"
    
    # How to use it in your code:
    # plt.savefig("monthly_spending.png", dpi=150, bbox_inches='tight')
    # report_content += embed_image("monthly_spending.png")
    # report_content += "\\n\\n*Insight: Spending peaks in December due to holiday purchases, with a notable dip in January reflecting post-holiday budget consciousness.*\\n\\n"
    ```

* **For every table or chart you generate, you **must** immediately follow it with a concise, 1-2 line 
summary of the key insight or observation. Your job is to **interpret the financial data**, not just display it.

---

### Workflow 2: Specific Questions

If the request is **specific**, your goal is to write Python code that directly calculates or visualizes 
the answer to the user's question using the financial data. Generate and show any plots/graphs as PNG files, 
but do not create a markdown report.

* **For every table or chart you generate, you **must** immediately 
follow it with a concise, 1-2 line summary of the key insight or observation related to spending patterns.

---

### Universal Rules for All Tasks

No matter which workflow you use, you **must always** follow these rules for execution:

1.  **Plan:** Start with a brief explanation of your approach and whether this is a broad or specific question.
2.  **Load Data First:** Always start by loading the `combined_data.json` file and exploring its structure.
3.  **Write Python Code:** Provide all Python code in proper code blocks.
    ```python
    # Your code here
    ```
4.  **Wait for Execution:** After writing code, pause and wait for the code executor agent's response.
5.  **Install Libraries:** If a library is missing, provide a `bash` command to install it, then resend the unchanged Python code.
    ```bash
    pip install pandas matplotlib seaborn numpy
    ```
6.  **Save and Show Plots:** All plots must be saved as PNG files with high DPI (150+) and displayed.
7.  **Final Answer:** Once all tasks are complete, provide a final, comprehensive explanation of the financial insights discovered, followed by the word **STOP**.

Remember: You are analyzing financial spending data, so focus on spending patterns, trends, categories, and merchant analysis. Always provide actionable insights about spending behavior.
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
    
    # Load and validate the data
    try:
        combined_data = load_combined_data(json_file_path)
        print(f"Successfully loaded data from: {json_file_path}")
        print(f"Data contains {len(combined_data.get('combined_transactions_by_cardholder', {}))} cardholders")
    except Exception as e:
        print(f"Error loading data: {e}")
        return
    
    # Create model client
    model_client = AnthropicChatCompletionClient(
        model=ANTHROPIC_MODEL, 
        api_key=ANTHROPIC_API_KEY
    )
    
    # Create data analyzer agent
    data_analyzer = AssistantAgent(
        name="data_analyzer", 
        model_client=model_client,
        system_message=DATA_ANALYZER_SYSTEM_MESSAGE,
        reflect_on_tool_use=True
    )
    
    # Create code executor
    code_executor = DockerCommandLineCodeExecutor(
        work_dir=".",  # Use current directory
        image="python:3.11-slim"  # Specify Python image
    )
    await code_executor.start()
    
    # Create code executor agent
    executor_agent = CodeExecutorAgent(
        name="code_executor",
        code_executor=code_executor
    )
    
    # Create the team with termination condition
    termination_condition = TextMentionTermination("STOP")
    analysis_team = RoundRobinGroupChat(
        participants=[data_analyzer, executor_agent],
        termination_condition=termination_condition
    )
    
    # Prepare the initial task message with the JSON file path and user question
    initial_message = f"""
I have a combined financial data JSON file at: {json_file_path}

The data structure contains:
- combined_transactions_by_cardholder: All transactions organized by cardholder with categories
- summary_by_bank: Aggregated data by bank
- summary_by_cardholder: Aggregated data by cardholder  
- category_totals: Overall spending by category
- individual_statements: Raw data from each processed statement

User Question: {user_question}

Please analyze this financial data and provide insights based on the question asked.
"""
    
    task = TextMessage(
        content=initial_message,
        source="user"
    )
    
    print("=" * 60)
    print("FINANCIAL DATA ANALYSIS STARTING")
    print("=" * 60)
    print(f"Question: {user_question}")
    print(f"Data Source: {json_file_path}")
    print("=" * 60)
    
    # Run the analysis
    try:
        result = await Console(analysis_team.run_stream(task=task))
        print("\n" + "=" * 60)
        print("ANALYSIS COMPLETED")
        print("=" * 60)
        
        # Check if a report was generated
        report_files = list(Path(".").glob("*report*.md"))
        if report_files:
            print(f"\nGenerated reports: {[str(f) for f in report_files]}")
        
        # Check for generated plots
        plot_files = list(Path(".").glob("*.png"))
        if plot_files:
            print(f"Generated plots: {[str(f) for f in plot_files]}")
            
    except Exception as e:
        print(f"Error during analysis: {e}")
    finally:
        # Clean up
        await code_executor.stop()
        print("\nAnalysis session ended.")

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
    
    # Run the analyzer
    asyncio.run(run_data_analyzer(args.json_file, args.question))

if __name__ == "__main__":
    main()

# Example usage:
# python data_analyzer.py combined_parsed_data.json "Analyze the spending data"
# python data_analyzer.py combined_parsed_data.json "What is the total spending on Food & Dining?"
# python data_analyzer.py combined_parsed_data.json "Show me the top 5 merchants by spending"
"""Data analyzer agent for generating financial reports."""

import json
import shutil
from pathlib import Path
from autogen_agentchat.agents import AssistantAgent, CodeExecutorAgent
from autogen_agentchat.teams import RoundRobinGroupChat
from autogen_agentchat.conditions import MaxMessageTermination, TextMentionTermination
from autogen_agentchat.messages import TextMessage
from autogen_ext.code_executors.docker import DockerCommandLineCodeExecutor
from autogen_agentchat.ui import Console

from config.models import get_openai_client
from config.constants import TEMP_DIR, FINAL_OUTPUT_DIR, OPENAI_MODEL
from utils.data_combiner import load_combined_data
from agents.prompts.data_analyzer_message import DATA_ANALYZER_SYSTEM_MESSAGE



async def run_data_analyzer(json_file_path: str, user_question: str):
    """Run the data analyzer with the given JSON file and user question."""
    
    # # Validate input file exists
    # if not Path(json_file_path).exists():
    #     raise FileNotFoundError(f"JSON file not found: {json_file_path}")

    # Copy the JSON file to ensure it's accessible in the Docker container
    try:
        # Ensure the data file is in the temp directory where Docker can see it
        source_path = Path(json_file_path)
        dest_path = Path(TEMP_DIR) / 'combined_data.json'
        
        if source_path != dest_path:
            shutil.copy2(source_path, dest_path)
            print(f"✅ Copied data file to Docker working directory: {dest_path}")
        
        # Also validate the file
        with open(dest_path, 'r') as f:
            test_data = json.load(f)
            tx_count = sum(len(txs) for txs in test_data.get('combined_transactions_by_cardholder', {}).values())
            print(f"✅ Validated data: {tx_count} transactions found")
    except Exception as e:
        print(f"⚠️ Failed to copy/validate data file: {e}")
        return

    # Load the data to validate it
    try:
        data = load_combined_data(dest_path)
        print(f"✅ Data file validated: {len(data)} top-level keys found")
    except Exception as e:
        print(f"⚠ Error loading data: {e}")
        return
    
    # Create model client
    model_client = get_openai_client()
    
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
        image="amancevice/pandas",  
        # image="demisto/pandas", 
        timeout=1200  
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
    max_message_termination = MaxMessageTermination(max_messages=50)  # Increased limit
    
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
    
    # # Copy the JSON file to ensure it's accessible in the Docker container
    # try:
    #     # Read and write to ensure the file is in the working directory
    #     with open(json_file_path, 'r') as src:
    #         data_content = src.read()
    #     with open('./combined_data.json', 'w') as dst:
    #         dst.write(data_content)
    #     print(f"✅ Copied data file to working directory: ./combined_data.json")
    # except Exception as e:
    #     print(f"⚠ Failed to copy data file: {e}")
    #     return

    # Prepare the initial task message
    initial_message = f"""
    I have a combined financial data JSON file at: {TEMP_DIR}/combined_data.json
    The file contains {tx_count} transactions across multiple cardholders.

    User Question: {user_question}

    Please analyze this financial data and provide insights based on the question asked.

    IMPORTANT: 
    - Start by verifying you can load the data file and print the number of transactions found
    - Your Python script must include extensive print statements to show progress and results
    - Always validate the data structure before proceeding with analysis
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
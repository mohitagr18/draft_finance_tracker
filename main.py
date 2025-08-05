import asyncio
from pathlib import Path
import sys # Used to exit if the file is not found
import json
from teams.analyzer_team import get_data_analyzer_team
from models.openai_model_client import get_model_client
from config.docker_util import get_docker_executor, start_docker_executor, stop_docker_executor
from autogen_agentchat.messages import TextMessage
from autogen_agentchat.base import TaskResult

async def main():
    # --- Step 1: Add your PDF to the 'temp' folder ---
    pdf_filename = "test_statement.pdf" # Make sure this matches your file name

    # --- Code execution starts here ---
    temp_dir = Path("temp")
    test_pdf_path = temp_dir / pdf_filename

    if not test_pdf_path.is_file():
        print(f"❌ Error: File not found at '{test_pdf_path}'")
        sys.exit(1)

    print(f"✅ Found file: {test_pdf_path}. Starting agent team...")

    docker_executor = get_docker_executor()
    model_client = get_model_client()
    team = get_data_analyzer_team(model_client, docker_executor)
    
    
    final_json_output = None

    try:
        await start_docker_executor(docker_executor)

        task = f"Please process the PDF file at path '{test_pdf_path}' and extract all transaction data into structured JSON format. The file contains financial statement data that needs to be parsed and standardized."

        # --- Updated Loop for Clearer Logging ---
        message_count = 0
        task_delegated = False
        last_speaker = None
        start_time = asyncio.get_event_loop().time()
        timeout_seconds = 120  # 2 minutes timeout
        print("🔄 Starting conversation stream...")
        async for message in team.run_stream(task=task):
            # Check timeout
            current_time = asyncio.get_event_loop().time()
            if current_time - start_time > timeout_seconds:
                print(f"⏰ Timeout reached ({timeout_seconds}s). Stopping conversation.")
                break
            message_count += 1
            print(f"📨 Message #{message_count} - Type: {type(message)}")
            
            # Debug: Check what type of message we're getting
            if not isinstance(message, TextMessage):
                print(f"🔍 Non-text message type: {type(message)}")
                print(f"🔍 Message content: {message}")
                continue  # Skip non-text messages for now
            
            if isinstance(message, TextMessage):
                # It's a regular message from an agent
                agent_name = message.source
                content = message.content
                last_speaker = agent_name

                print(f"--- Speaker: {agent_name} (Turn #{message_count}) ---")
                print(content)
                print("\n" + "="*80 + "\n")

                # Check if this message contains our final JSON
                
                # Track planning agent behavior
                if agent_name == 'Planning_Agent':
                    if 'TERMINATE' in content.upper():
                        if not task_delegated:
                            print("⚠️ Planning agent is saying TERMINATE before task was delegated!")
                        else:
                            print("✅ Planning agent is terminating after task completion")
                    elif 'File_Processor_Agent:' in content:
                        task_delegated = True
                        print("✅ Planning agent delegated task to File_Processor_Agent")
                        print("🔄 Next turn should be File_Processor_Agent to process the task")
                
                # Track File_Processor_Agent behavior
                    
                
                if agent_name == 'File_Processor_Agent' and isinstance(content, str) and content.strip().startswith('['):
                    print("✅ File_Processor_Agent is now processing the task")
                    try:
                        json.loads(content)
                        final_json_output = content
                        print("✅ Found JSON output from File_Processor_Agent")
                    except json.JSONDecodeError:
                        pass # Not valid JSON, ignore

            elif isinstance(message, TaskResult):
                # The task has finished
                print(f"--- Task Finished ---")
                print(f"Stop Reason: {message.stop_reason}")
                # print(f"Last Message: {message.last_message.content if message.last_message else 'None'}")
                
                # # Check if the last message contains JSON
                # if message.last_message and message.last_message.content:
                #     content = message.last_message.content
                #     if isinstance(content, str) and content.strip().startswith('['):
                #         try:
                #             json.loads(content)
                #             final_json_output = content
                #             print("✅ Found JSON output in final message")
                #         except json.JSONDecodeError:
                #             pass

                print("\n" + "="*80 + "\n")


    except Exception as e:
        print(f"An error occurred during agent execution: {e}")
    finally:
        await stop_docker_executor(docker_executor)

    # --- Print the Final JSON Result ---
    if final_json_output:
        print("\n🎉 Final JSON Output from File_Processor_Agent: 🎉")
        # Pretty print the JSON
        parsed_json = json.loads(final_json_output)
        print(json.dumps(parsed_json, indent=2))
    else:
        print("\n⚠️ Could not retrieve final JSON output from the File_Processor_Agent.")

if __name__ == "__main__":
    asyncio.run(main())
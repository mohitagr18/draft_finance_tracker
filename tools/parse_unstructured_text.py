import asyncio
import json
from autogen_agentchat.agents import AssistantAgent, CodeExecutorAgent
from autogen_agentchat.messages import TextMessage
from autogen_agentchat.teams import RoundRobinGroupChat
from autogen_agentchat.conditions import TextMentionTermination, MaxMessageTermination
from agents.prompts.unstructured_text_parser_message import UNSTRUCTURED_TEXT_PARSER_SYSTEM_MESSAGE
from typing import List, Dict

async def parse_unstructured_text(unstructured_text: str, model_client, code_executor_instance) -> str:
    """
    Parses unstructured text by orchestrating a conversational and self-correcting
    process between a code-writing agent and a code-executing agent.

    Args:
        unstructured_text (str): The raw text extracted from a PDF.
        model_client: The language model client for the code-writing agent.
        code_executor_instance: The configured Docker code executor instance.

    Returns:
        str: A JSON string of the extracted transactions, or an error JSON.
    """
    
    # Print the input text for debugging
    print("\n" + "="*60)
    print("UNSTRUCTURED TEXT INPUT TO PARSER:")
    print("="*60)
    print(repr(unstructured_text))  # Using repr() to show escape characters
    print("="*60)
    print("UNSTRUCTURED TEXT (FORMATTED):")
    print("="*60)
    print(unstructured_text)
    print("="*60)
    print(f"TEXT LENGTH: {len(unstructured_text)} characters")
    print(f"LINE COUNT: {len(unstructured_text.splitlines())} lines")
    print("="*60)
    
    # Enhanced system message with stricter instructions
    enhanced_system_message = UNSTRUCTURED_TEXT_PARSER_SYSTEM_MESSAGE + """

CRITICAL INSTRUCTIONS:
1. ALWAYS use the EXACT unstructured text provided in the user message - NEVER use sample data
2. Write Python code that processes the actual input text, not placeholder text
3. Start each response with a brief plan of what you're doing or fixing
4. When you have working code that produces valid JSON, include both the final code AND say "PARSING_COMPLETE"
5. Focus on extracting real transaction data from the provided text
6. If the text extraction works but produces empty results, still output the empty JSON array []
7. NEVER respond with just "PARSING_COMPLETE" - always include code when executor needs it
"""
    
    # 1. Define the agents for the conversational sub-task
    code_writer = AssistantAgent(
        name="Code_Writer",
        model_client=model_client,
        system_message=enhanced_system_message,
    )

    code_executor_agent = CodeExecutorAgent(
        name="Code_Executor",
        code_executor=code_executor_instance
    )

    # 2. Create termination conditions that allow for proper conversation
    termination_condition = MaxMessageTermination(20)  # Simplified - only use max messages
    
    team = RoundRobinGroupChat([code_writer, code_executor_agent], termination_condition=termination_condition)

    # 3. Create a more specific task message
    task_message = TextMessage(
        content=f"""Your task is to write Python code that parses the following ACTUAL TEXT and extracts financial transactions as JSON.

REQUIREMENTS:
- Use the EXACT text provided below (not sample data)
- Extract ALL transaction-like entries from this specific text
- Output a JSON array of transactions with fields: date, description, amount
- After successful execution, respond with "PARSING_COMPLETE"

TEXT TO PARSE (USE THIS EXACT TEXT):
---START OF ACTUAL TEXT---
{unstructured_text}
---END OF ACTUAL TEXT---

Write Python code to process this exact text and extract transaction data.""",
        source="user"
    )

    # 4. Run the conversation with enhanced monitoring
    chat_history = []
    print("\n--- Code Writer and Executor Conversation ---")
    
    valid_json_found = None
    consecutive_no_code = 0
    parsing_complete_found = False
    
    try:
        async for message in team.run_stream(task=task_message):
            chat_history.append(message)
            
            if hasattr(message, 'source') and hasattr(message, 'content'):
                print(f"Speaker: {message.source}")
                print(f"Content:\n{message.content}")
                print("-" * 50)
                
                content = getattr(message, 'content', '')
                
                # Check for valid JSON in executor messages
                if message.source == "Code_Executor" and isinstance(content, str):
                    # Look for JSON array output
                    json_match = None
                    try:
                        # Find JSON array in the content
                        start_idx = content.find('[')
                        end_idx = content.rfind(']')
                        if start_idx != -1 and end_idx != -1 and start_idx < end_idx:
                            potential_json = content[start_idx:end_idx+1]
                            parsed_json = json.loads(potential_json)  # Validate
                            json_match = potential_json
                            print(f"\n✅ Valid JSON found with {len(parsed_json)} transactions")
                            print(f"JSON preview: {potential_json[:200]}...")
                            valid_json_found = json_match
                    except json.JSONDecodeError as e:
                        print(f"JSON decode error: {e}")
                        pass
                    
                    # Check for "No code blocks found" message
                    if "No code blocks found" in content:
                        consecutive_no_code += 1
                        print(f"Consecutive 'no code' messages: {consecutive_no_code}")
                        
                        # If we have valid JSON and get "no code blocks", we're done
                        if valid_json_found:
                            print(f"\n✅ Terminating: Have valid JSON and executor says no code blocks")
                            break
                    else:
                        consecutive_no_code = 0
                
                # Check for completion signals from code writer AND valid JSON
                if message.source == "Code_Writer" and isinstance(content, str):
                    if "PARSING_COMPLETE" in content:
                        parsing_complete_found = True
                        print(f"\n✅ Code writer signals completion")
                        
                        # Only stop if we ALSO have valid JSON from executor
                        if valid_json_found:
                            print(f"\n✅ Terminating: Have both valid JSON and completion signal")
                            break
                        else:
                            print(f"\n⚠️ Code writer says complete but no valid JSON found yet - continuing")
                
                # Stop conversation if we get multiple rounds of "no code blocks" after having JSON
                if (valid_json_found and consecutive_no_code >= 2):
                    print(f"\n✅ Terminating: Have valid JSON and executor requesting code repeatedly")
                    break
                    
                # Emergency stop for too many messages
                if len(chat_history) >= 18:  # Stop before hitting the termination condition
                    print(f"\n⚠️ Emergency stop: Approaching maximum messages ({len(chat_history)}/20)")
                    break
                    
    except Exception as e:
        print(f"Error during conversation: {e}")
        return json.dumps({"error": f"Conversation failed: {str(e)}"})

    # 5. Extract the final result
    print(f"\n--- CONVERSATION ENDED ---")
    print(f"Total messages: {len(chat_history)}")
    print(f"Valid JSON found during conversation: {'Yes' if valid_json_found else 'No'}")
    print(f"Parsing complete signal: {'Yes' if parsing_complete_found else 'No'}")
    
    if valid_json_found:
        print(f"Valid JSON length: {len(valid_json_found)} characters")
        print(f"Valid JSON content: {valid_json_found}")
    
    print("---")
    
    if valid_json_found:
        print(f"\n--- Returning Valid JSON Found During Conversation ---")
        print(valid_json_found)
        print("-" * 50)
        return valid_json_found
    
    # Fallback: search through all messages for JSON
    print("\n--- FALLBACK: Searching all messages for JSON ---")
    for i, message in enumerate(reversed(chat_history)):
        print(f"Checking message {len(chat_history)-i}: {getattr(message, 'source', 'unknown')}")
        content = getattr(message, 'content', None)
        if isinstance(content, str):
            print(f"  Content length: {len(content)}")
            print(f"  Content preview: {content[:100]}...")
            
            # Look for JSON array
            start_index = content.find('[')
            end_index = content.rfind(']')
            if start_index != -1 and end_index != -1 and start_index < end_index:
                json_string = content[start_index:end_index+1]
                print(f"  Found potential JSON array: {len(json_string)} chars")
                try:
                    json.loads(json_string)
                    print(f"  ✅ Valid JSON found in fallback search!")
                    print(f"\n--- Final JSON from {getattr(message, 'source', 'unknown')} ---")
                    print(json_string)
                    print("-" * 50)
                    return json_string
                except json.JSONDecodeError as e:
                    print(f"  ❌ JSON decode failed: {e}")
                    continue
                    
            # Also check for JSON objects
            start_index = content.find('{')
            end_index = content.rfind('}')
            if start_index != -1 and end_index != -1 and start_index < end_index:
                json_string = content[start_index:end_index+1]
                print(f"  Found potential JSON object: {len(json_string)} chars")
                try:
                    json.loads(json_string)
                    print(f"  ✅ Valid JSON object found in fallback search!")
                    print(f"\n--- Final JSON Object from {getattr(message, 'source', 'unknown')} ---")
                    print(json_string)
                    print("-" * 50)
                    return json_string
                except json.JSONDecodeError as e:
                    print(f"  ❌ JSON decode failed: {e}")
                    continue
        else:
            print(f"  Content is not string: {type(content)}")

    print("\n--- Error: Could not extract valid JSON ---")
    print("--- DEBUG: Printing all message contents ---")
    for i, message in enumerate(chat_history):
        print(f"Message {i+1} from {getattr(message, 'source', 'unknown')}:")
        content = getattr(message, 'content', None)
        print(f"  Type: {type(content)}")
        print(f"  Content: {content}")
        print("-" * 30)
    
    return json.dumps({"error": "Could not extract valid JSON from the conversation."})



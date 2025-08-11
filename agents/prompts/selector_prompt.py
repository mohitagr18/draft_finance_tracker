SELECTOR_PROMPT = """

Based on the conversation below, select the next agent to speak.

Conversation:
{history}

Available agents: {participants}

DECISION RULES:
- If Planning_Agent just delegated a task (look for "File_Processor_Agent: <task>"), select File_Processor_Agent
- If File_Processor_Agent just provided JSON output, select Planning_Agent  
- If no task has been delegated yet, select Planning_Agent
- If any agent says "TERMINATE", stop

Your selection: {participants}

"""

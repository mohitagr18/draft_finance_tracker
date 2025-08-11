from autogen_agentchat.teams import SelectorGroupChat
from autogen_agentchat.conditions import TextMentionTermination
from agents.planning_agent import get_planning_agent
from agents.file_processor_agent import get_file_processor_agent
from agents.prompts.selector_prompt import SELECTOR_PROMPT

def get_data_analyzer_team(model_client, code_executor):

    planning_agent = get_planning_agent(model_client)

    file_processor_agent = get_file_processor_agent(model_client, code_executor)

    # Use simple termination condition
    text_mention_termination = TextMentionTermination('TERMINATE')

    team = SelectorGroupChat(
        participants=[planning_agent, file_processor_agent],
        model_client=model_client,
        termination_condition=text_mention_termination,
        selector_prompt=SELECTOR_PROMPT,
        allow_repeated_speaker=True,  # Allow an agent to speak multiple turns in a row.
        max_turns=20  # Allow more turns for processing
    )
    
    return team
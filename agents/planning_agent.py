from autogen_agentchat.agents import AssistantAgent
from agents.prompts.planning_agent_message import PLANNING_AGENT_SYSTEM_MESSAGE

def get_planning_agent(model_client):

    planning_agent = AssistantAgent(
        name="Planning_Agent",
        model_client=model_client,
        system_message=PLANNING_AGENT_SYSTEM_MESSAGE,
        description="An agent for planning tasks, this agent should be the first to engage when given a new task."
    )
    
    return planning_agent
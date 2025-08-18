"""Custom termination conditions for autogen agents."""

from typing import Sequence

from autogen_agentchat.base import TerminationCondition
from autogen_agentchat.messages import BaseAgentEvent, BaseChatMessage, StopMessage

from utils.json_utils import extract_json_from_text
from utils.data_combiner import has_categories


class JSONSuccessTermination(TerminationCondition):
    """Terminates when valid JSON is found in executor output."""
    
    def __init__(self):
        self._terminated = False
    
    @property
    def terminated(self) -> bool:
        return self._terminated
    
    async def __call__(self, messages: Sequence[BaseAgentEvent | BaseChatMessage]) -> StopMessage | None:
        if self._terminated:
            return None
            
        # Check the messages for executor output with valid JSON
        for msg in reversed(messages[-3:]):  # Check last 3 messages
            if getattr(msg, "source", "") == "executor":
                content = getattr(msg, "content", "")
                if extract_json_from_text(content) is not None:
                    self._terminated = True
                    return StopMessage(
                        content="Valid JSON found in executor output.",
                        source="JSONSuccessTermination"
                    )
        return None
    
    async def reset(self) -> None:
        self._terminated = False


class CategorizationSuccessTermination(TerminationCondition):
    """Terminates when categorized JSON is found in categorizer output."""
    
    def __init__(self):
        self._terminated = False
    
    @property
    def terminated(self) -> bool:
        return self._terminated
    
    async def __call__(self, messages: Sequence[BaseAgentEvent | BaseChatMessage]) -> StopMessage | None:
        if self._terminated:
            return None
            
        # Check the messages for categorizer output with valid JSON containing categories
        for msg in reversed(messages[-2:]):  # Check last 2 messages
            if getattr(msg, "source", "") == "categorizer":
                content = getattr(msg, "content", "")
                parsed_json = extract_json_from_text(content)
                if parsed_json and has_categories(parsed_json):
                    self._terminated = True
                    return StopMessage(
                        content="Categorized JSON found in categorizer output.",
                        source="CategorizationSuccessTermination"
                    )
        return None
    
    async def reset(self) -> None:
        self._terminated = False
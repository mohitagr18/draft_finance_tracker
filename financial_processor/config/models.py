"""Model client configuration and validation."""

from autogen_ext.models.openai import OpenAIChatCompletionClient
from autogen_ext.models.anthropic import AnthropicChatCompletionClient
from .constants import (
    ANTHROPIC_MODEL, 
    ANTHROPIC_API_KEY, 
    OPENAI_MODEL, 
    OPENAI_API_KEY
)


def validate_api_keys():
    """Validate that required API keys are present."""
    missing_keys = []
    
    if not ANTHROPIC_API_KEY:
        missing_keys.append("ANTHROPIC_API_KEY")
    if not OPENAI_API_KEY:
        missing_keys.append("OPENAI_API_KEY2")
    
    if missing_keys:
        raise EnvironmentError(
            f"Please set the following environment variables: {', '.join(missing_keys)}"
        )


def get_anthropic_client():
    """Get configured Anthropic model client."""
    validate_api_keys()
    return AnthropicChatCompletionClient(
        model=ANTHROPIC_MODEL, 
        api_key=ANTHROPIC_API_KEY
    )


def get_openai_client():
    """Get configured OpenAI model client."""
    validate_api_keys()
    return OpenAIChatCompletionClient(
        model=OPENAI_MODEL, 
        api_key=OPENAI_API_KEY
    )


def get_model_clients():
    """Get both model clients."""
    return get_anthropic_client(), get_openai_client()
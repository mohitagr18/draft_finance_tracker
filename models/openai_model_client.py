from autogen_ext.models.openai import OpenAIChatCompletionClient
from config.constants import MODEL_OPENAI
import os
from dotenv import load_dotenv
load_dotenv()

def get_model_client():

    openai_model_client = OpenAIChatCompletionClient(
        api_key=os.getenv("OPENAI_API_KEY2"),
        model=MODEL_OPENAI
    )
    return openai_model_client

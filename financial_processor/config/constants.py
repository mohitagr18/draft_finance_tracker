"""Configuration constants for the financial processor."""

import os
from dotenv import load_dotenv

load_dotenv()

# === CONFIGURATION ===

# Model configuration
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")  
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY2")

# Directory configuration
TEMP_DIR = "temp"
OUTPUT_DIR = "temp/parsed_statements"
FINAL_OUTPUT_DIR = "output"
# COMBINED_JSON_FILE = "combined_parsed_data.json"
COMBINED_JSON_FILE = os.path.join(TEMP_DIR, "combined_data.json")
"""File handling utilities."""

import glob
from pathlib import Path


def load_statement(file_path: str) -> str:
    """Load statement text from file."""
    with open(file_path, "r", encoding="utf-8") as f:
        return f.read()


def ensure_output_dir(output_dir: str):
    """Create output directory if it doesn't exist."""
    Path(output_dir).mkdir(parents=True, exist_ok=True)


def get_statement_files(pattern: str) -> list:
    """Get list of statement files matching the pattern."""
    files = glob.glob(pattern)
    files.sort()  # Sort for consistent processing order
    return files


def ensure_directories(*dirs):
    """Ensure multiple directories exist."""
    for directory in dirs:
        Path(directory).mkdir(parents=True, exist_ok=True)
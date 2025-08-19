TASK_MESSAGE = """
Please write Python code to parse the following bank statement text and extract transaction data as JSON.

Start your code with this helper function for package management:
```python
import subprocess
import sys
import importlib

def ensure_package(package_name, import_name=None):
    \"\"\"Ensure a package is installed and import it.\"\"\"
    if import_name is None:
        import_name = package_name
    
    try:
        return importlib.import_module(import_name)
    except ImportError:
        print(f"Installing {{package_name}}...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", package_name])
        return importlib.import_module(import_name)

# Example usage:
# pd = ensure_package("pandas")
# plt = ensure_package("matplotlib", "matplotlib.pyplot")

Here is the bank statement content to parse:

{statement_text}

Use the helper function to install any packages you need, then write code to parse the statement text into structured JSON.
"""
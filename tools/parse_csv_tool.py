import pandas as pd
import json

def parse_csv_file(file_path: str) -> str:
    """
    Reads a CSV bank statement, attempts to identify common transaction columns,
    and returns the data as a JSON string.

    This tool is designed to handle CSV files with common column names like
    'Date', 'Transaction', 'Description', 'Amount', 'Credit', 'Debit'.

    Args:
        file_path (str): The local path to the CSV file.

    Returns:
        str: A JSON string representing a list of transaction dictionaries.
             Returns an error message string if parsing fails.
    """
    try:
        df = pd.read_csv(file_path)
        
        # --- Column Name Identification Logic ---
        # Standardize column names to lowercase for easier matching
        df.columns = [col.lower() for col in df.columns]

        # Define potential aliases for our target columns
        date_aliases = ['date', 'transaction date']
        desc_aliases = ['description', 'transaction', 'details']
        amount_aliases = ['amount', 'debit', 'credit']

        # Find the actual column names in the DataFrame
        date_col = next((col for col in df.columns if col in date_aliases), None)
        desc_col = next((col for col in df.columns if col in desc_aliases), None)
        
        # For amount, we might have separate debit/credit columns
        debit_col = next((col for col in df.columns if col == 'debit'), None)
        credit_col = next((col for col in df.columns if col == 'credit'), None)
        amount_col = next((col for col in df.columns if col == 'amount'), None)

        if not date_col or not desc_col:
            return json.dumps({"error": "Could not automatically identify date or description columns."})

        # --- Data Extraction and Formatting ---
        transactions = []
        for index, row in df.iterrows():
            transaction = {
                "date": row[date_col],
                "description": row[desc_col],
                "amount": None
            }

            # Handle different amount representations
            if amount_col:
                transaction["amount"] = row[amount_col]
            elif debit_col and credit_col:
                # Combine debit/credit into a single amount column
                # Debits are negative, credits are positive
                debit = pd.to_numeric(row[debit_col], errors='coerce') or 0
                credit = pd.to_numeric(row[credit_col], errors='coerce') or 0
                transaction["amount"] = credit - debit
            
            if transaction["amount"] is not None:
                transactions.append(transaction)

        return json.dumps(transactions, indent=2)

    except Exception as e:
        return json.dumps({"error": f"Failed to parse CSV file: {str(e)}"})



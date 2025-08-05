import pandas as pd
import json
from typing import List, Dict, Union

def standardize_data(json_data: str) -> str:
    """
    Takes a JSON string of transactions, cleans the data, sorts it,
    and returns the standardized data as a JSON string.

    Standardization includes:
    1. Converting date strings to a consistent 'YYYY-MM-DD' format.
    2. Ensuring the 'amount' field is a numeric type (float).
    3. Sorting all transactions chronologically by date.

    Args:
        json_data (str): A JSON string representing a list of transaction objects.
                         Each object must have 'date', 'description', and 'amount'.

    Returns:
        str: A cleaned, sorted, and standardized JSON string of transactions.
    """
    try:
        transactions: List[Dict[str, Union[str, float]]] = json.loads(json_data)
        
        # --- Data Cleaning and Type Conversion ---
        for t in transactions:
            # Convert amount to float, handling potential errors
            t['amount'] = float(t.get('amount', 0))
            
            # Convert date to datetime object for sorting, then back to 'YYYY-MM-DD' string
            # This handles various common date formats like 'MM/DD/YY', 'MM-DD-YYYY', etc.
            t['date'] = pd.to_datetime(t['date'], errors='coerce').strftime('%Y-%m-%d')

        # Remove any transactions where date conversion failed
        transactions = [t for t in transactions if t['date'] != 'NaT']

        # --- Sorting ---
        # Sort the list of dictionaries by the 'date' key
        sorted_transactions = sorted(transactions, key=lambda t: t['date'])

        return json.dumps(sorted_transactions, indent=2)

    except (json.JSONDecodeError, TypeError, KeyError) as e:
        return json.dumps({"error": f"Failed to standardize data: {str(e)}"})


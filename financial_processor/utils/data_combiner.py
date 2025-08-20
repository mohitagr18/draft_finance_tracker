"""Data combination utilities for bank statement processing."""

import json
from pathlib import Path
from typing import List


def combine_parsed_data(individual_files: List[str]) -> dict:
    """Combine multiple parsed JSON files into a single structure with detailed breakdowns."""
    combined = {
        "combined_transactions_by_cardholder": {},
        "individual_statements": [],
        "combined_summary": {
            "total_files_processed": 0,
            "total_transactions": 0,
            "total_amount": 0.0,
            "total_purchases": 0.0,
            "total_payments": 0.0
        },
        "summary_by_bank": {},
        "summary_by_cardholder": {},
        "category_totals": {}
    }
    
    for file_path in individual_files:
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Add to individual statements
            filename = Path(file_path).stem
            combined["individual_statements"].append({
                "filename": filename,
                "data": data
            })
            
            # Get bank name from summary
            bank_name = data.get("summary", {}).get("bank_name", "Unknown Bank")
            
            # Initialize bank summary if not exists
            if bank_name not in combined["summary_by_bank"]:
                combined["summary_by_bank"][bank_name] = {
                    "total_statements": 0,
                    "total_transactions": 0,
                    "total_amount": 0.0,
                    "total_purchases": 0.0,
                    "total_payments": 0.0,
                    "cardholders": []
                }
            
            # Merge transactions by cardholder and calculate totals
            if "transactions_by_cardholder" in data:
                for cardholder, transactions in data["transactions_by_cardholder"].items():
                    # Skip empty or non-list values to reduce garbage
                    if not isinstance(transactions, list) or not transactions:
                        continue
                    # Initialize cardholder in combined transactions
                    if cardholder not in combined["combined_transactions_by_cardholder"]:
                        combined["combined_transactions_by_cardholder"][cardholder] = []
                    combined["combined_transactions_by_cardholder"][cardholder].extend(transactions)
                    
                    # Initialize cardholder summary if not exists
                    if cardholder not in combined["summary_by_cardholder"]:
                        combined["summary_by_cardholder"][cardholder] = {
                            "total_transactions": 0,
                            "total_amount": 0.0,
                            "total_purchases": 0.0,
                            "total_payments": 0.0,
                            "banks": {},
                            "category_totals": {}
                        }
                    
                    # Add cardholder to bank's list if not already there
                    if cardholder not in combined["summary_by_bank"][bank_name]["cardholders"]:
                        combined["summary_by_bank"][bank_name]["cardholders"].append(cardholder)
                    
                    # Initialize bank for this cardholder if not exists
                    if bank_name not in combined["summary_by_cardholder"][cardholder]["banks"]:
                        combined["summary_by_cardholder"][cardholder]["banks"][bank_name] = {
                            "total_transactions": 0,
                            "total_amount": 0.0,
                            "total_purchases": 0.0,
                            "total_payments": 0.0
                        }
                    
                    # Process each transaction
                    cardholder_transaction_count = 0
                    cardholder_total_amount = 0.0
                    cardholder_purchases = 0.0
                    cardholder_payments = 0.0
                    
                    for transaction in transactions:
                        if isinstance(transaction, dict):
                            amount = transaction.get("amount", 0)
                            category = transaction.get("category", "Uncategorized")
                            
                            cardholder_transaction_count += 1
                            cardholder_total_amount += amount
                            
                            # Categorize as purchase or payment (payments are typically negative)
                            if amount < 0:
                                cardholder_payments += abs(amount)
                            else:
                                cardholder_purchases += amount
                            
                            # Update category totals for cardholder
                            if category not in combined["summary_by_cardholder"][cardholder]["category_totals"]:
                                combined["summary_by_cardholder"][cardholder]["category_totals"][category] = 0.0
                            combined["summary_by_cardholder"][cardholder]["category_totals"][category] += amount
                            
                            # Update overall category totals
                            if category not in combined["category_totals"]:
                                combined["category_totals"][category] = 0.0
                            combined["category_totals"][category] += amount
                    
                    # Update cardholder totals
                    combined["summary_by_cardholder"][cardholder]["total_transactions"] += cardholder_transaction_count
                    combined["summary_by_cardholder"][cardholder]["total_amount"] += cardholder_total_amount
                    combined["summary_by_cardholder"][cardholder]["total_purchases"] += cardholder_purchases
                    combined["summary_by_cardholder"][cardholder]["total_payments"] += cardholder_payments
                    
                    # Update cardholder's bank-specific totals
                    combined["summary_by_cardholder"][cardholder]["banks"][bank_name]["total_transactions"] += cardholder_transaction_count
                    combined["summary_by_cardholder"][cardholder]["banks"][bank_name]["total_amount"] += cardholder_total_amount
                    combined["summary_by_cardholder"][cardholder]["banks"][bank_name]["total_purchases"] += cardholder_purchases
                    combined["summary_by_cardholder"][cardholder]["banks"][bank_name]["total_payments"] += cardholder_payments
            
            # Update bank summary from statement summary
            if "summary" in data:
                summary = data["summary"]
                combined["summary_by_bank"][bank_name]["total_statements"] += 1
                combined["summary_by_bank"][bank_name]["total_transactions"] += summary.get("total_transactions", 0)
                combined["summary_by_bank"][bank_name]["total_amount"] += summary.get("total_amount", 0)
                combined["summary_by_bank"][bank_name]["total_purchases"] += summary.get("purchases", 0)
                combined["summary_by_bank"][bank_name]["total_payments"] += summary.get("payments", 0)
                
                # Update combined summary
                combined["combined_summary"]["total_files_processed"] += 1
                combined["combined_summary"]["total_transactions"] += summary.get("total_transactions", 0)
                combined["combined_summary"]["total_amount"] += summary.get("total_amount", 0)
                combined["combined_summary"]["total_purchases"] += summary.get("purchases", 0)
                combined["combined_summary"]["total_payments"] += summary.get("payments", 0)
                
        except Exception as e:
            print(f"Error reading {file_path}: {e}")
    
    return combined


def has_categories(json_obj: dict) -> bool:
    """Check if JSON contains categorized transactions."""
    try:
        transactions_by_cardholder = json_obj.get("transactions_by_cardholder", {})
        for cardholder, transactions in transactions_by_cardholder.items():
            if isinstance(transactions, list) and len(transactions) > 0:
                # Check if at least one transaction has a category
                for transaction in transactions:
                    if isinstance(transaction, dict) and "category" in transaction:
                        return True
        return False
    except Exception:
        return False
    

def load_combined_data(file_path: str) -> dict:
    """Load the combined financial data JSON file."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        raise ValueError(f"Error loading combined data file: {e}")
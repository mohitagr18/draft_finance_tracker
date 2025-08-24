TASK_MESSAGE = """
Parse the comprehensive bank statement file 'statement.txt' containing multiple statement formats and extract ALL transaction data accurately.

CONTEXT:
The statement text will be provided after these instructions. Your code should:
1. Assign the provided text to a variable called 'statement_text'
2. Parse ALL cardholders (e.g., MOHIT AGGARWAL, HIMANI SOOD)
3. Extract ALL transactions with both sale_date and post_date in MM/DD format
4. Handle multiple statement formats (Citi, Capital One, etc.)
5. Output complete JSON with all transactions organized by cardholder

CRITICAL: 
- Each transaction MUST have both 'sale_date' and 'post_date' fields
- If only one date is found, use it for BOTH fields
- All dates must be in MM/DD format (e.g., "07/14", "12/25")
- Parse ALL sections, not just the first few transactions
"""


# TASK_MESSAGE = """
# Parse the bank statement file 'statement.txt' into structured JSON format.

# The file contains credit card statement data with:
# - Multiple cardholders (e.g., MOHIT AGGARWAL, HIMANI SOOD) 
# - Transaction sections for each cardholder
# - Account summary with balances and totals

# Your code should:
# 1. Install required packages (json, re)
# 2. Read the statement.txt file 
# 3. Extract cardholder names from proper sections (not random text)
# 4. Parse transactions with dates, descriptions, and amounts
# 5. Extract summary data from account summary sections
# 6. Output clean JSON structure

# Focus on accuracy - extract real cardholder names and actual transactions, not headings or boilerplate text.

# Examples of what to extract:
# - Cardholders: "MOHIT AGGARWAL" (from cardholder sections)
# - Transactions: "07/05 07/05 HEADWAY HEADWAY.CO NY $10.00"
# - Summary: Previous balance, New balance, Payments, etc.

# Write complete, working Python code that produces the required JSON output.
# """
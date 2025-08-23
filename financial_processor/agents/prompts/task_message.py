TASK_MESSAGE = """
Parse the comprehensive bank statement file 'statement.txt' containing multiple statement formats and extract ALL transaction data accurately.

CONTEXT:
The file contains credit card statements from different banks (Citi, Capital One, etc.) with:
- Multiple cardholders per statement (e.g., MOHIT AGGARWAL, HIMANI SOOD)
- Different transaction section formats
- Varying date formats (MM/DD, MMM DD, MM/DD/YY)
- Multiple summary layouts

CRITICAL REQUIREMENTS:
1. Extract ALL cardholders - not just the first one found
2. Parse ALL transactions for each cardholder across all statement formats
3. Handle different section headers:
   - "Standard Purchases" (Citi format)
   - "CARDHOLDER_NAME #XXXX: Transactions" (Capital One format)
   - "CARDHOLDER_NAME #XXXX: Payments, Credits and Adjustments"
4. Identify correct bank names from statement headers, not cardholder names
5. Parse different date formats consistently

EXPECTED OUTPUT SCALE:
Based on the provided statements, you should extract:
- 2+ cardholders (MOHIT AGGARWAL, HIMANI SOOD, etc.)
- 40+ total transactions across all cardholders
- Accurate bank identification
- Complete summary data from account summary sections

VALIDATION CHECKS:
- Each major cardholder should have multiple transactions (10-20+ each)
- Transaction totals should align with statement summaries when possible
- Bank name should be actual financial institution, not person name
- All date formats should be parsed consistently

Write complete Python code with robust parsing logic that handles the complexity and variation in bank statement formats. Focus on comprehensive extraction rather than just parsing the first few transactions found.

Install any required packages and implement thorough parsing that captures the full scope of financial data present.
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
# BEGIN INSERT: Quality Gate Helpers
import re
import json

def _extract_possible_cardholders(src: str) -> set:
    names = set()
    # Patterns like "<NAME>\nCard ending in ####"
    for m in re.finditer(r'\n\s*([A-Z][A-Z]+(?:\s+[A-Z][A-Z]+)+)\s*\n\s*(?:Card|Account)\s+ending\s+in\s+\d{3,4}', src):
        names.add(m.group(1).strip())
    # Uppercase names in CARDHOLDER SUMMARY sections
    for m in re.finditer(r'CARDHOLDER SUMMARY.*?\n\s*([A-Z][A-Z]+(?:\s+[A-Z][A-Z]+)+)\s*(?:\n|$)', src, flags=re.DOTALL):
        names.add(m.group(1).strip())
    names.discard("PRIMARY ACCOUNT HOLDER")
    return names

def _valid_date(s: str) -> bool:
    return bool(re.match(r'^\d{1,2}/\d{1,2}(?:/\d{2,4})?$', s.strip()))

def _valid_amount(v) -> bool:
    try:
        f = float(v)
        return f != 0.0 and abs(f) < 1e8
    except (ValueError, TypeError):
        return False

def _is_heading_like(desc: str) -> bool:
    txt = desc.strip().lower()
    if len(txt) < 3: return True
    heading_snippets = [
        "summary", "amount", "description", "sale", "post", "fees charged",
        "interest charged", "rewards", "total", "card by", "billing inquiries",
        "customer service", "minimum payment", "payment due date", "credit limit"
    ]
    return any(sn in txt for sn in heading_snippets)

def _source_signals(raw_text: str) -> dict:
    t = raw_text
    brand_re = r'\b(visa|master ?card|amex|discover|citi|chase|bank of america|wells fargo)\b'
    structure_terms = ["statement", "account summary", "new balance", "payment due date"]
    has_brand = bool(re.search(brand_re, t, flags=re.I))
    has_structure = any(s in t.lower() for s in structure_terms)
    has_last4 = bool(re.search(r'(?:ending in|acct.*ending\s*in)\s*\d{3,4}', t, flags=re.I))
    date_hits = len(re.findall(r'\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b', t))
    money_hits = len(re.findall(r'\$\s?\d[\d,]*\.\d{2}', t))
    return {"has_brand": has_brand, "has_structure": has_structure, "has_last4": has_last4, "date_hits": date_hits, "money_hits": money_hits}

def quality_gate(raw_text: str, parsed: dict, retry_level: int = 0) -> tuple[bool, str, dict]:
    if not isinstance(parsed, dict):
        return False, "Parsed result is not a dict.", {}
    tx_map = parsed.get("transactions_by_cardholder", {})
    if not isinstance(tx_map, dict):
        return False, "Missing or invalid 'transactions_by_cardholder'.", {}

    # Strictness knobs by retry level: 0=strict, 1=normal, 2=relaxed
    level = max(0, min(2, int(retry_level)))
    min_date_hits, min_money_hits = [5, 3, 2][level], [3, 2, 1][level]
    require_both_dates, require_known_holder = [True, True, False][level], [True, False, False][level]

    allowed_names, cleaned_map, total_tx = _extract_possible_cardholders(raw_text), {}, 0

    for holder, txs in tx_map.items():
        if require_known_holder and allowed_names and holder not in allowed_names: continue
        if not isinstance(txs, list) or not txs: continue

        cleaned_txs = []
        for t in txs:
            if not isinstance(t, dict): continue
            sale, post, desc, amt = str(t.get("sale_date","")), str(t.get("post_date","")), str(t.get("description","")), t.get("amount")
            
            sale_ok, post_ok = _valid_date(sale), _valid_date(post)
            if require_both_dates and not (sale_ok and post_ok): continue
            if not require_both_dates and not (sale_ok or post_ok): continue
            
            if not require_both_dates: # If one date is valid, mirror it
                if sale_ok and not post_ok: t["post_date"] = sale
                elif post_ok and not sale_ok: t["sale_date"] = post

            if _is_heading_like(desc) or len(desc.strip()) < 2 or not _valid_amount(amt): continue
            
            t["amount"] = float(amt)
            cleaned_txs.append(t)
        
        if cleaned_txs:
            cleaned_map[holder], total_tx = cleaned_txs, total_tx + len(cleaned_txs)

    parsed["transactions_by_cardholder"] = cleaned_map
    sig = _source_signals(raw_text)
    signal_score = sum([sig["has_brand"], sig["has_structure"], sig["has_last4"], sig["date_hits"] >= min_date_hits, sig["money_hits"] >= min_money_hits])

    if total_tx == 0:
        return False, "No valid transactions after cleanup.", {}
    if signal_score < 2 and level == 0:
        return False, "Source text lacks recognizable statement signals.", {}

    # Coerce summary fields to numeric types
    summary = parsed.get("summary", {})
    if isinstance(summary, dict):
        for k in ["previous_balance", "new_balance", "payments", "credits", "purchases"]:
            if k in summary and summary[k] not in (None, ""):
                try: summary[k] = float(summary[k])
                except (ValueError, TypeError): summary[k] = 0.0
        parsed["summary"] = summary
        
    return True, "OK", parsed
# END INSERT


# import re
# import json

# def _extract_possible_cardholders(src: str) -> set:
#     """Extracts likely cardholder names using common statement patterns."""
#     names = set()
#     # Common patterns: " <NAME>\nCard ending in ####" or " <NAME>\nAccount ending in ####"
#     for m in re.finditer(r'\n\s*([A-Z][A-Z]+(?:\s+[A-Z][A-Z]+)+)\s*\n\s*(?:Card|Account)\s+ending\s+in\s+\d{3,4}', src):
#         names.add(m.group(1).strip())
#     # Fallback: uppercase full-name lines in “CARDHOLDER SUMMARY” blocks
#     for m in re.finditer(r'CARDHOLDER SUMMARY.*?\n\s*([A-Z][A-Z]+(?:\s+[A-Z][A-Z]+)+)\s*(?:\n|$)', src, flags=re.DOTALL):
#         names.add(m.group(1).strip())
#     # Avoid overly generic “PRIMARY ACCOUNT HOLDER” unless explicitly present
#     names.discard("PRIMARY ACCOUNT HOLDER")
#     return names

# def _valid_date(s: str) -> bool:
#     """Checks if a string matches a common date format (e.g., MM/DD, MM/DD/YYYY)."""
#     return bool(re.match(r'^\d{1,2}/\d{1,2}(?:/\d{2,4})?$', s.strip()))

# def _valid_amount(v) -> bool:
#     """Checks if a value can be converted to a non-zero float."""
#     try:
#         f = float(v)
#         return f != 0.0 and abs(f) < 1e8
#     except Exception:
#         return False

# def _is_heading_like(desc: str) -> bool:
#     """Checks if a description string resembles a table heading or boilerplate."""
#     txt = desc.strip().lower()
#     if len(txt) < 3:
#         return True
#     heading_snippets = [
#         "summary", "amount", "description", "sale", "post", "fees charged",
#         "interest charged", "rewards", "total", "card by", "billing inquiries",
#         "customer service", "minimum payment", "payment due date", "credit limit"
#     ]
#     return any(sn in txt for sn in heading_snippets)

# def _source_signals(raw_text: str) -> dict:
#     """Detects generic signals to determine if the source text is a bank statement."""
#     t = raw_text
#     brand_re = r'\b(visa|master ?card|american express|amex|discover|capital one|citi|citibank|chase|bank of america|wells fargo|synchrony|barclays|hsbc|td bank|pnc|us bank|usaa|navy federal|fidelity|elancobank)\b'
#     structure_terms = [
#         "statement", "billing period", "account summary", "previous balance",
#         "new balance", "minimum payment", "payment due date", "credit limit",
#         "available credit"
#     ]
#     has_brand = bool(re.search(brand_re, t, flags=re.I))
#     has_structure = any(s in t.lower() for s in structure_terms)
#     has_last4 = bool(re.search(r'(?:ending in|acct(?:ount)?\s*(?:no\.?|number)?\s*ending\s*in)\s*\d{3,4}', t, flags=re.I))
#     date_hits = len(re.findall(r'\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b', t))
#     money_hits = len(re.findall(r'\$\s?\d[\d,]*\.\d{2}', t))
#     return {
#         "has_brand": has_brand,
#         "has_structure": has_structure,
#         "has_last4": has_last4,
#         "date_hits": date_hits,
#         "money_hits": money_hits,
#     }

# def quality_gate(raw_text: str, parsed: dict) -> tuple[bool, str, dict]:
#     """
#     Performs bank-agnostic validation and cleanup on parsed statement data.
#     Returns a tuple: (is_ok, message, cleaned_dict_or_empty).
#     """
#     if not isinstance(parsed, dict):
#         return False, "Parsed result is not a dictionary.", {}

#     tx_map = parsed.get("transactions_by_cardholder", {})
#     if not isinstance(tx_map, dict):
#         return False, "Missing or invalid 'transactions_by_cardholder' key.", {}

#     allowed_names = _extract_possible_cardholders(raw_text)
#     cleaned_map = {}
#     total_tx = 0

#     # Clean and validate each transaction
#     for holder, txs in tx_map.items():
#         if allowed_names and holder not in allowed_names:
#             continue
#         if not isinstance(txs, list) or not txs:
#             continue

#         cleaned_txs = []
#         for t in txs:
#             if not isinstance(t, dict): continue
#             sale, post = str(t.get("sale_date", "")), str(t.get("post_date", ""))
#             desc, amt = str(t.get("description", "")), t.get("amount")

#             if not (_valid_date(sale) and _valid_date(post)): continue
#             if _is_heading_like(desc) or len(desc.strip()) < 2: continue
#             if not _valid_amount(amt): continue
            
#             t["amount"] = float(amt)
#             cleaned_txs.append(t)
        
#         if cleaned_txs:
#             cleaned_map[holder] = cleaned_txs
#             total_tx += len(cleaned_txs)

#     parsed["transactions_by_cardholder"] = cleaned_map

#     # Check for multiple independent signals that the source is a real statement
#     sig = _source_signals(raw_text)
#     signal_score = sum([
#         sig["has_brand"], sig["has_structure"], sig["has_last4"],
#         sig["date_hits"] >= 5, sig["money_hits"] >= 3
#     ])

#     if total_tx == 0:
#         return False, "No valid transactions found after cleanup.", {}
#     if signal_score < 2:
#         return False, "Source text lacks sufficient signals of being a bank statement.", {}

#     # Optional: ensure summary numbers are numeric
#     summary = parsed.get("summary", {})
#     if isinstance(summary, dict):
#         for k in ["previous_balance", "payments", "credits", "purchases", "new_balance"]:
#             if k in summary and summary[k] is not None:
#                 try:
#                     summary[k] = float(summary[k])
#                 except (ValueError, TypeError):
#                     summary[k] = 0.0
#         parsed["summary"] = summary

#     return True, "OK", parsed
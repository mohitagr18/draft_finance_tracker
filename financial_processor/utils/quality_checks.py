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

# Enhanced quality_gate function with comprehensive debugging
def quality_gate(raw_text: str, parsed: dict, retry_level: int = 0) -> tuple[bool, str, dict]:
    """Enhanced quality gate with detailed debugging."""
    
    print(f"\n=== QUALITY GATE DEBUG (retry_level={retry_level}) ===")
    
    if not isinstance(parsed, dict):
        print("❌ Parsed result is not a dict")
        return False, "Parsed result is not a dict.", {}
    
    tx_map = parsed.get("transactions_by_cardholder", {})
    if not isinstance(tx_map, dict):
        print("❌ Missing or invalid 'transactions_by_cardholder'")
        return False, "Missing or invalid 'transactions_by_cardholder'.", {}

    print(f"📊 Raw cardholder data: {list(tx_map.keys())}")
    
    # Show sample of raw transactions before processing
    for holder, txs in list(tx_map.items())[:2]:  # Show first 2 cardholders
        print(f"\n🔍 RAW DATA for '{holder}':")
        if isinstance(txs, list) and txs:
            for i, tx in enumerate(txs[:3]):  # Show first 3 transactions
                print(f"  Transaction {i}: {tx}")
        else:
            print(f"  No transactions or invalid format: {type(txs)}")
    
    allowed_names = _extract_possible_cardholders(raw_text)
    print(f"🔍 Allowed cardholder names from source: {allowed_names}")
    
    # Strictness settings
    level = max(0, min(2, int(retry_level)))
    min_date_hits, min_money_hits = [5, 3, 2][level], [3, 2, 1][level]
    require_both_dates, require_known_holder = [True, True, False][level], [True, False, False][level]
    
    print(f"⚙️  Quality level: {['strict', 'normal', 'relaxed'][level]}")
    print(f"⚙️  Require known holder: {require_known_holder}")
    print(f"⚙️  Require both dates: {require_both_dates}")

    cleaned_map, total_tx = {}, 0

    for holder, txs in tx_map.items():
        print(f"\n👤 Processing holder: '{holder}'")
        
        # More flexible name matching
        holder_match = False
        if require_known_holder and allowed_names:
            # Exact match
            if holder in allowed_names:
                holder_match = True
            # Partial match (handle case differences, extra spaces)
            else:
                for allowed in allowed_names:
                    if allowed.replace(' ', '').lower() in holder.replace(' ', '').lower():
                        holder_match = True
                        print(f"   ✅ Matched '{holder}' to allowed name '{allowed}'")
                        break
                    if holder.replace(' ', '').lower() in allowed.replace(' ', '').lower():
                        holder_match = True
                        print(f"   ✅ Matched '{holder}' to allowed name '{allowed}'")
                        break
            
            if not holder_match:
                print(f"   ❌ Skipped: '{holder}' not in allowed names {allowed_names}")
                continue
        else:
            holder_match = True  # No restriction
            
        if not isinstance(txs, list):
            print(f"   ❌ Skipped: transactions not a list, got {type(txs)}")
            continue
            
        if not txs:
            print(f"   ⚠️  Empty transaction list")
            continue

        print(f"   📝 Processing {len(txs)} transactions")
        cleaned_txs = []
        
        for i, t in enumerate(txs):
            if not isinstance(t, dict): 
                print(f"      Transaction {i}: ❌ Not a dict, got {type(t)}")
                continue
                
            # Get transaction fields with fallbacks
            sale = str(t.get("sale_date", t.get("date", "")))  # Fallback to 'date' field
            post = str(t.get("post_date", t.get("date", "")))  # Fallback to 'date' field
            desc = str(t.get("description", ""))
            amt = t.get("amount")
            
            # Validate dates
            sale_ok = _valid_date(sale) if sale else False
            post_ok = _valid_date(post) if post else False
            
            print(f"      Transaction {i}:")
            print(f"        sale='{sale}' ✅{sale_ok}, post='{post}' ✅{post_ok}")
            print(f"        desc='{desc[:40]}{'...' if len(desc) > 40 else ''}'")
            print(f"        amt={amt} (type: {type(amt)})")
            
            # Date validation with relaxed requirements for retry levels
            if require_both_dates and not (sale_ok and post_ok):
                print(f"        ❌ Invalid dates (both required)")
                continue
            if not require_both_dates and not (sale_ok or post_ok):
                print(f"        ❌ Invalid dates (at least one required)")
                continue
            
            # Mirror dates if only one is valid
            if not require_both_dates:
                if sale_ok and not post_ok:
                    t["post_date"] = sale
                    post = sale
                    post_ok = True
                elif post_ok and not sale_ok:
                    t["sale_date"] = post
                    sale = post
                    sale_ok = True
                print(f"        📋 After mirroring: sale='{sale}', post='{post}'")

            # Description validation
            if _is_heading_like(desc):
                print(f"        ❌ Heading-like description")
                continue
                
            if len(desc.strip()) < 2:
                print(f"        ❌ Description too short")
                continue
                
            # Amount validation
            if not _valid_amount(amt):
                print(f"        ❌ Invalid amount: {amt}")
                continue
            
            # Clean and add transaction
            t["amount"] = float(amt)
            t["sale_date"] = sale
            t["post_date"] = post
            cleaned_txs.append(t)
            print(f"        ✅ Valid transaction added")
        
        if cleaned_txs:
            cleaned_map[holder] = cleaned_txs
            total_tx += len(cleaned_txs)
            print(f"   ✅ Added {len(cleaned_txs)} valid transactions for '{holder}'")
        else:
            print(f"   ❌ No valid transactions for '{holder}'")

    print(f"\n📊 FINAL RESULTS:")
    print(f"   Total transactions: {total_tx}")
    print(f"   Total cardholders: {len(cleaned_map)}")
    for holder, txs in cleaned_map.items():
        print(f"   - {holder}: {len(txs)} transactions")
    
    # Source signals check
    sig = _source_signals(raw_text)
    signal_score = sum([sig["has_brand"], sig["has_structure"], sig["has_last4"], 
                       sig["date_hits"] >= min_date_hits, sig["money_hits"] >= min_money_hits])
    
    print(f"\n🔍 SOURCE SIGNALS: {sig}")
    print(f"📊 Signal score: {signal_score}/5 (need ≥2 for strict level)")

    parsed["transactions_by_cardholder"] = cleaned_map

    # Final validation
    if total_tx == 0:
        print("❌ FINAL RESULT: No valid transactions after cleanup")
        return False, "No valid transactions after cleanup.", {}
        
    if signal_score < 2 and level == 0:
        print("❌ FINAL RESULT: Source lacks statement signals (strict mode only)")
        return False, "Source text lacks recognizable statement signals.", {}

    # Process summary
    summary = parsed.get("summary", {})
    if isinstance(summary, dict):
        print(f"\n💰 Processing summary: {summary}")
        for k in ["previous_balance", "new_balance", "payments", "credits", "purchases"]:
            if k in summary and summary[k] not in (None, ""):
                try: 
                    old_val = summary[k]
                    summary[k] = float(summary[k])
                    print(f"   {k}: {old_val} -> {summary[k]}")
                except (ValueError, TypeError): 
                    print(f"   {k}: failed to convert {summary[k]} to float")
                    summary[k] = 0.0
        parsed["summary"] = summary
        
    print("✅ FINAL RESULT: Quality gate PASSED")
    print(f"=== END QUALITY GATE DEBUG ===\n")
    return True, "OK", parsed
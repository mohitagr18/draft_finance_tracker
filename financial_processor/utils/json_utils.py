"""JSON processing utilities."""

import json
import re


def extract_json_from_text(text: str):
    """Return parsed JSON object found in text or None."""
    if not text or not isinstance(text, str):
        return None

    # strip common code fences
    text2 = re.sub(r"```(?:json|python)?", "", text, flags=re.IGNORECASE)

    # Try quick parse if text is (mostly) JSON
    stripped = text2.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        try:
            return json.loads(stripped)
        except Exception:
            pass

    # Find first balanced {...} substring and try parsing progressively
    start = text2.find("{")
    while start != -1:
        depth = 0
        for i in range(start, len(text2)):
            ch = text2[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    candidate = text2[start:i+1]
                    # try parse
                    try:
                        return json.loads(candidate)
                    except Exception:
                        # parsing failed; continue searching for next '{'
                        break
        start = text2.find("{", start + 1)
    return None
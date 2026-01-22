import re
from typing import Optional

ROLE_WORDS = {
    "executor",
    "executrix",
    "administrator",
    "administratrix",
    "trustee",
    "fiduciary",
    "legatee",
    "residuary",
    "beneficiary",
    "nominated",
    "successor",
}

ADDRESS_DUPES = [
    (r"(?i)\bSS\s+Staten\s+Island\b", "Staten Island"),
    (r"(?i)\bStaten\s+Island\s+Staten\s+Island\b", "Staten Island"),
    (r"(?i)\bNew,\s*YORK\b", "New York"),
]

ADDRESS_FIXES = [
    (r"(?i)Bouleva\s*rd", "Boulevard"),
    (r"(?i)We\s*st", "West"),
    (r"(?i)ISLAND\s+ISLAND", "Island"),
]


def clean_email(val: str) -> str:
    if not val:
        return ""
    m = re.search(r"([A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,})", val, re.IGNORECASE)
    return m.group(1).lower() if m else ""


def clean_phone(val: str) -> str:
    if not val:
        return ""
    digits = re.sub(r"\D", "", val)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) != 10:
        return ""
    return f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"


def clean_person_name(val: str) -> str:
    if not val:
        return ""
    val = re.sub(r"\b([A-Z])\b$", "", val).strip()
    tokens = [t for t in re.split(r"\s+", val) if t]
    tokens = [t for t in tokens if t.lower() not in ROLE_WORDS]
    return " ".join(tokens).strip(" ,;")


def clean_address(val: str) -> str:
    if not val:
        return ""
    out = val
    for pat, repl in ADDRESS_DUPES + ADDRESS_FIXES:
        out = re.sub(pat, repl, out)
    # drop role words
    out = re.sub(r"(?i)\b(" + "|".join(ROLE_WORDS) + r")\b", "", out)
    out = re.sub(r"\s+", " ", out)
    out = out.replace(" ,", ",").strip(" ,;")
    return out


def clean_money(val: Optional[str]) -> str:
    if not val:
        return ""
    digits = re.sub(r"[,$\s]", "", str(val))
    if digits.isdigit():
        return digits
    m = re.search(r"(\d{3,})", digits)
    return m.group(1) if m else ""

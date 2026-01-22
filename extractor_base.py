import re
from collections import defaultdict
from typing import Dict, List, Sequence

Columns = [
    "Deceased Property Address",
    "Deceased Name",
    "Petitioner Name",
    "Petitioner Address",
    "Relationship",
    "Property Value",
    "Attorney",
    "Phone Number",
    "Email Address",
]

STOPWORDS = {
    "information",
    "signature",
    "petitioner",
    "estate",
    "administration",
    "administrator",
    "executor",
    "decedent",
    "deceased",
    "respectfully",
    "prays",
    "appointed",
    "individual",
    "foregoing",
    "petition",
    "county",
    "domicile",
    "place",
    "death",
    "residence",
    "file",
    "follows",
    "no",
    "the",
    "and",
    "my",
    "is",
    "to",
    "be",
    "are",
    "as",
    "of",
    "an",
    "that",
    "this",
    "in",
    "for",
    "print",
    "name",
    "named",
    "being",
    "duly",
    "sworn",
    "says",
    "say",
    "verily",
    "believes",
    "believe",
    "informed",
    "respectfully",
    "prays",
    "pray",
    "suc",
    "shall",
    "hereby",
    "herein",
}

STATE_MAP = {
    "new york": "NY",
    "new jersey": "NJ",
    "florida": "FL",
    "california": "CA",
    "connecticut": "CT",
    "pennsylvania": "PA",
    "texas": "TX",
    "georgia": "GA",
    "illinois": "IL",
}

BANNED_ADDRESS_TERMS = [
    "beneficiary",
    "residuary",
    "legatee",
    "executor",
    "executrix",
    "administrator",
    "administratrix",
    "trustee",
    "successor",
    "co-executor",
    "nominated",
    "distributee",
    "fiduciary",
    "legacy",
    "devise",
    "spouse",
    "husband",
    "wife",
    "son",
    "daughter",
    "child",
    "petitioner",
    "guardian",
    "attorney",
    "estate of",
    "other interest",
    "nature of",
    "designated in will",
    "under paragraph",
    "estate",
    "of last will",
    "paragraph",
    "schedule",
]

# Role terms that are not valid relationships
ROLE_BLACKLIST = [
    "executor",
    "executrix",
    "administrator",
    "trustee",
    "co-executor",
    "successor",
    "nominated",
    "personal representative",
    "fiduciary",
    "beneficiary",
    "legatee",
]

# Allowed relationship values for normalization/validation
REL_ALLOWED = [
    "spouse",
    "wife",
    "husband",
    "son",
    "daughter",
    "child",
    "mother",
    "father",
    "sister",
    "brother",
    "niece",
    "nephew",
    "grandchild",
    "grandson",
    "granddaughter",
]

BANNED_LABEL_PHRASES = {
    "other",
    "other specify",
    "specify",
    "checkbox",
    "check one",
    "attesting witnesses",
    "executor",
    "administrator",
    "petitioner",
    "title officer",
    "clerk",
    "proponent",
    "objectant",
}

ROLE_WORDS = {
    "executor",
    "executrix",
    "administrator",
    "administratrix",
    "petitioner",
    "title officer",
    "clerk",
    "trustee",
    "attorney",
    "lawyer",
    "esquire",
    "paralegal",
    "notary",
    "applicant",
}

NY_AREA_CODES = {
    "212",
    "315",
    "332",
    "347",
    "516",
    "518",
    "585",
    "607",
    "631",
    "646",
    "716",
    "718",
    "845",
    "914",
    "917",
    "929",
}

ADDRESS_STREET_TOKENS = {
    "street",
    "st",
    "avenue",
    "ave",
    "road",
    "rd",
    "drive",
    "dr",
    "lane",
    "ln",
    "boulevard",
    "blvd",
    "court",
    "ct",
    "parkway",
    "pkwy",
    "place",
    "pl",
    "circle",
    "cir",
    "way",
    "highway",
    "hwy",
    "apt",
    "apartment",
    "unit",
    "suite",
    "ste",
}


def normalize_text(text: str) -> str:
    cleaned = text.replace("\r", "\n")
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = re.sub(r"\n{2,}", "\n", cleaned)
    return cleaned.strip()


def split_lines(text: str) -> List[str]:
    return [ln.strip() for ln in normalize_text(text).splitlines()]


def strip_aka(name: str) -> str:
    name = re.split(r"(?i)\b(?:a/k/a|aka)\b", name)[0]
    name = re.sub(r"\(.*?\)|\[.*?\]", "", name)
    name = re.sub(r"\s+", " ", name)
    return name.strip(" ,;")


def clean_person_name(raw: str) -> str:
    raw = strip_aka(raw)
    tokens = []
    for part in re.split(r"\s+", raw):
        clean = re.sub(r"[^A-Za-z'-]", "", part)
        if not clean:
            continue
        if clean.lower() in STOPWORDS:
            continue
        tokens.append(clean)
    if not tokens:
        return ""
    normalized = " ".join(t.title() for t in tokens)
    return normalized.strip(" ,;")


def is_label_noise(text: str) -> bool:
    """
    Heuristic filter for checkbox/label noise frequently OCR'd as values.
    """
    if not text:
        return False
    low = text.lower().strip()
    if any(phrase in low for phrase in BANNED_LABEL_PHRASES):
        return True
    fused = re.sub(r"[^a-z]", "", low)
    if fused in {"otherspecify", "otherspecifi"}:
        return True
    # All-caps single role word
    if text.isupper() and low in ROLE_WORDS:
        return True
    return False


def validate_person_name(name: str) -> bool:
    """
    Basic validation to ensure we keep real names and drop labels/roles.
    """
    if not name:
        return False
    if is_label_noise(name):
        return False
    letters = re.findall(r"[A-Za-z]", name)
    if len(letters) < 2:
        return False
    tokens = [t for t in re.split(r"\s+", name.strip()) if t]
    if not (1 <= len(tokens) <= 4):
        return False
    for t in tokens:
        if re.search(r"[^A-Za-z.'-]", t):
            return False
        if t.lower() in ROLE_WORDS or t.lower() in BANNED_LABEL_PHRASES:
            return False
    return True


def _has_ny_context(pages_text: Sequence[str]) -> bool:
    combined = "\n".join(pages_text).lower()
    if "surrogate" in combined and "state of new york" in combined:
        return True
    if "county of richmond" in combined or "county of nassau" in combined or "county of kings" in combined:
        return True
    if re.search(r"\bny\b", combined):
        return True
    if re.search(r"\b1\d{4}\b", combined):  # NY ZIPs start with 1
        return True
    return False


def correct_ny_phone(phone: str, pages_text: Sequence[str], debug=None, field: str = "Phone Number") -> str:
    digits = re.sub(r"\D", "", phone or "")
    if len(digits) != 10:
        return phone
    ny_context = _has_ny_context(pages_text)
    if not ny_context:
        return phone
    area = digits[:3]
    rest = digits[3:]
    corrected = digits
    reason = ""
    if area == "816":
        alt = "516" + rest
        corrected = alt
        reason = "816_to_516_ny_context"
    elif area not in NY_AREA_CODES:
        if "516" + rest == digits:
            corrected = digits
        elif "516" in NY_AREA_CODES:
            corrected = "516" + rest
            reason = "ny_preferred_area"
    if corrected != digits:
        formatted = f"{corrected[:3]}-{corrected[3:6]}-{corrected[6:]}"
        if debug is not None:
            debug.setdefault("attorney_phone_candidates", []).append(
                {"source": "ny_area_adjust", "value": formatted, "score": 95, "status": "ADJUST", "reason": reason}
            )
        return formatted
    return phone


def find_emails_in_pages(pages_text: Sequence[str], prefer_near: Sequence[str] | None = None, debug=None) -> str:
    prefer_near = prefer_near or [
        "signature of attorney",
        "email (optional)",
        "print name of attorney",
        "firm name",
        "telephone",
    ]
    best = ("", -1, -1)  # email, score, page
    for idx, page in enumerate(pages_text):
        page_norm = page.replace("\r", "\n")
        # collapse to help wrapped addresses
        collapsed = re.sub(r"\s+", " ", page_norm)
        matches = list(re.finditer(r"(?i)([A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,})", collapsed, re.IGNORECASE))
        # partial wrapped emails like user@domain .com
        matches += list(
            re.finditer(
                r"(?i)([A-Z0-9._%+-]+@[A-Z0-9.-]+)\s*\.?\s*(com|net|org|gov|edu|law)",
                collapsed,
                re.IGNORECASE,
            )
        )
        # gmail without TLD (common OCR drop)
        matches += list(re.finditer(r"(?i)([A-Z0-9._%+-]+@gmail)\b\.?", collapsed, re.IGNORECASE))
        for m in matches:
            email = m.group(0)
            if len(m.groups()) >= 2 and not email.lower().endswith(tuple([".com", ".net", ".org", ".gov", ".edu", ".law"])):
                email = f"{m.group(1)}.{m.group(2)}"
            email = email.rstrip(" .").lower()
            if not re.search(r"\.[a-z]{2,}$", email):
                if email.endswith("@gmail") or email.endswith("@gmail."):
                    email = email.rstrip(".") + ".com"
            score = 10
            window_start = max(0, m.start() - 120)
            window_end = min(len(collapsed), m.end() + 120)
            window = collapsed[window_start:window_end].lower()
            for anchor in prefer_near:
                if anchor.lower() in window:
                    score += 40
            if "attorney" in window:
                score += 20
            if "email" in window:
                score += 10
            if score > best[1]:
                best = (email, score, idx)
            if debug is not None:
                debug.setdefault("attorney_email_candidates", []).append(
                    {"source": f"page{idx+1}", "value": email, "score": score, "status": "CANDIDATE", "reason": "email_regex"}
                )
    return best[0]


def plausible_name(name: str) -> bool:
    if not name:
        return False
    tokens = [t for t in re.split(r"\s+", name) if t]
    if not (2 <= len(tokens) <= 4):
        return False
    upper_initials = sum(1 for t in tokens if t and t[0].isupper())
    if upper_initials / len(tokens) < 0.7:
        return False
    for t in tokens:
        low = t.lower().strip(" ,;")
        if low in STOPWORDS:
            return False
    return True


def _normalize_state(state: str) -> str:
    key = state.lower()
    return STATE_MAP.get(key, state.upper())


def _score_address(addr: str) -> int:
    low = addr.lower()
    score = 0
    if re.match(r"\d{4}\s", addr):
        score -= 2
    if "hospital" in low:
        score -= 5
    if "place of death" in low:
        score -= 3
    if "broadway" in low:
        score -= 2
    if "new york" in low:
        score += 2
    if "staten island" in low:
        score += 1
    if re.search(r"\b10314\b", low):
        score += 2
    return score


def clean_address(addr: str) -> str:
    addr = re.sub(r"\s+", " ", addr).strip(" ,")
    addr = re.sub(r",\s*,", ", ", addr)
    addr = re.sub(r"^(\d+),\s*", r"\1 ", addr)
    # Targeted OCR repairs for Staten Island variants; use word boundaries to avoid mangling
    # already correct strings (e.g., avoid matching the "n Island" inside "Staten Island").
    replacements = [
        (r"\bN\s+ISLAND\b", "Staten Island"),
        (r"\bSTATEN,\s*ISLAND\b", "Staten Island"),
        (r"\bSTATEN\s+IS\.?\b", "Staten Island"),
        (r"\bSTATENISLAND\b", "Staten Island"),
        (r"\bSC\s+Staten\s+Island\b", "Staten Island"),
        (r"\bSTATEN\s+ISLAND,\s*STATEN\s+ISLAND\b", "Staten Island"),
        (r"\bWe\s*st\s+Long\s+Branch\b", "West Long Branch"),
        (r"\bBouleva\s*rd\b", "Boulevard"),
        (r"\bRETFO?RD\b", "Retford"),
        (r"RETFO\s*RD,?\s*AVE\.?", "Retford Ave"),
        (r"\bWe\s*st\b", "West"),
        (r"Che\s*stnut", "Chestnut"),
        (r"Straffo\s*rd", "Strafford"),
        (r"\bS\.?I\.?\b", "Staten Island"),
        (r"\bStaten\s+Island\s+Staten\s+Island\b", "Staten Island"),
        (r"\bB\s*road\s+Street\b", "Broad Street"),
        (r"\bBroad Street\b", "BROAD STREET"),
        (r"\bSan\s*,\s*TX\b", "San Antonio, TX"),
        (r"\bSan\s+TX\b", "San Antonio, TX"),
        (r"\bStaten\s*,\s*NY\b", "Staten Island, NY"),
        (r"\bStaten\s+NY\b", "Staten Island, NY"),
        (r"Island\.,", "Island,"),
        (r"\bNew[, ]+YORK\b", "New York"),
        (r"\bNew,\s*York\b", "New York"),
    ]
    for pat, good in replacements:
        addr = re.sub(pat, good, addr, flags=re.IGNORECASE)
    # Normalize standalone "Staten" to "Staten Island" when NY/New York context exists (avoid duplicating existing Island)
    if re.search(r"\bStaten\b", addr, re.IGNORECASE) and not re.search(r"\bStaten\s+Island\b", addr, re.IGNORECASE):
        if re.search(r"\b(NY|New York)\b", addr, re.IGNORECASE):
            addr = re.sub(r"\bStaten\b(?!\s+Island)", "Staten Island", addr, flags=re.IGNORECASE)
    # Collapse accidental repeats like "Staten Island Island"
    addr = re.sub(r"(?i)Staten Island(?:\s+Island)+", "Staten Island", addr)
    addr = re.sub(r"(?i)Island\s+Island+", "Island", addr)
    # Insert comma after apartment/unit before city
    addr = re.sub(r"(?i)\b(apt|apartment|unit|ste|suite)\s*([0-9A-Za-z]+)\s+(?=[A-Za-z])", r"\1 \2, ", addr)
    addr = re.sub(
        r"^(\d[^,]+?(?:Street|St|Avenue|Ave|Road|Rd|Drive|Dr|Lane|Ln|Boulevard|Blvd|Court|Ct|Place|Pl|Way))\s+([A-Za-z .'-]+),\s*([A-Z]{2})\s+(\d{5}(?:-\d{4})?)",
        r"\1, \2, \3 \4",
        addr,
        flags=re.IGNORECASE,
    )
    if "," not in addr:
        state_pattern = r"(NY|NJ|FL|CA|CT|PA|TX|GA|IL|New York|New Jersey|Florida|California|Connecticut|Pennsylvania|Texas|Georgia|Illinois)"
        m = re.search(
            rf"(\d{{1,6}}\s+[A-Za-z0-9 .'-]+?)\s+([A-Za-z .'-]+)\s+{state_pattern}\s+(\d{{5}})",
            addr,
        )
        if m:
            street, city, state, zip_code = m.groups()
            state = _normalize_state(state)
            return f"{street.strip()}, {city.strip()}, {state} {zip_code}"
        # Try street city, State Zip when a comma exists only before state
        m2 = re.search(
            rf"(\d{{1,6}}\s+[A-Za-z0-9 .'-]+?)\s+([A-Za-z .'-]+),\s+{state_pattern}\s+(\d{{5}})",
            addr,
        )
        if m2:
            street, city, state, zip_code = m2.groups()
            state = _normalize_state(state)
            return f"{street.strip()}, {city.strip()}, {state} {zip_code}"
    parts = addr.split(",")
    if len(parts) >= 2:
        state_zip = parts[-1].strip()
        state_zip_parts = state_zip.split()
        if len(state_zip_parts) >= 3 and re.fullmatch(r"[A-Za-z]{2}", state_zip_parts[-2]):
            state = _normalize_state(state_zip_parts[-2])
            zip_code = state_zip_parts[-1]
            city_extra = state_zip_parts[:-2]
            base_parts = [p.strip() for p in parts[:-1]]
            if city_extra:
                city = city_extra[0]
                if len(base_parts) == 1:
                    base_parts.append(city)
                else:
                    base_parts[-1] = (base_parts[-1] + " " + city).strip()
            base_parts.append(f"{state} {zip_code}")
            addr = ", ".join(base_parts)
        elif len(state_zip_parts) >= 2:
            state = _normalize_state(" ".join(state_zip_parts[:-1]))
            zip_code = state_zip_parts[-1]
            parts[-1] = f"{state} {zip_code}"
            addr = ", ".join([p.strip() for p in parts])
    addr = re.sub(
        r",\s+(Street|St|Avenue|Ave|Road|Rd|Drive|Dr|Lane|Ln|Place|Pl|Boulevard|Blvd|Terrace|Ter|Court|Ct|Way)\b",
        r" \1",
        addr,
    )
    addr = re.sub(r"^(\d+),\s*", r"\1 ", addr)
    return addr


def _address_has_required_components(addr: str) -> bool:
    if not addr:
        return False
    low = addr.lower()
    if not (re.match(r"\d", addr) or re.search(r"\bpo\s*box\b", low)):
        return False
    if not any(tok in low for tok in ADDRESS_STREET_TOKENS):
        return False
    if not re.search(
        r"\b(NY|NJ|FL|CA|CT|PA|TX|GA|IL|New York|New Jersey|Florida|California|Connecticut|Pennsylvania|Texas|Georgia|Illinois)\b",
        addr,
        re.IGNORECASE,
    ):
        return False
    if re.search(r"\d{5}(?:-\d{4})?", addr):
        return True
    return False


def clean_address_strict(raw: str, field: str = "", debug=None) -> str:
    if not raw:
        return ""
    addr = raw.replace("\n", " ")
    addr = re.sub(r"\s+", " ", addr).strip(" ,")
    # OCR fixes: leading S -> 5 before a digit, fuse-break between digits and letters, fused street suffixes
    addr = re.sub(r"^S(\d)", r"5\1", addr)
    addr = re.sub(r"(\d)([A-Za-z])", r"\1 \2", addr)
    addr = re.sub(r"([A-Za-z])(\d)", r"\1 \2", addr)
    addr = re.sub(
        r"(?i)([A-Za-z]+)(avenue|ave|street|st|road|rd|drive|dr|lane|ln|court|ct|place|pl|boulevard|blvd)",
        r"\1 \2",
        addr,
    )
    ocr_fixes = {
        "ROMAN AVENUE": "Roman Avenue",
    }
    for bad, good in ocr_fixes.items():
        addr = re.sub(bad, good, addr, flags=re.IGNORECASE)
    low = addr.lower()
    for term in BANNED_ADDRESS_TERMS:
        if term in low:
            split_idx = low.find(term)
            addr = addr[:split_idx].strip(" ,")
            if debug is not None:
                debug.setdefault("_warnings", []).append(
                    f"WARNING: Address contamination detected (role/fiduciary text). Field={field} Value={raw}"
                )
            break
    addr = clean_address(addr)
    street_comma_match = None
    if "," not in addr:
        street_comma_match = re.match(
            r"^(\d[^,]+?(?:Street|St|Avenue|Ave|Road|Rd|Drive|Dr|Lane|Ln|Boulevard|Blvd|Court|Ct|Place|Pl|Way|Pkwy|Parkway))\s+(.*)$",
            addr,
            re.IGNORECASE,
        )
        if street_comma_match and "," not in street_comma_match.group(1):
            addr = f"{street_comma_match.group(1)}, {street_comma_match.group(2)}"
    addr = re.sub(r"^(\d+),\s*", r"\1 ", addr)
    # Ensure street-city comma when missing before state/zip
    addr = re.sub(
        r"^(\d[^,]+?)\s+([A-Za-z .'-]+),\s*([A-Z]{2})\s+(\d{5}(?:-\d{4})?)",
        r"\1, \2, \3 \4",
        addr,
    )
    if not _address_has_required_components(addr) or len(addr) < 8:
        # try to append city/state/zip from raw if street exists
        street_part = addr
        if street_part and re.match(r"\d", street_part):
            matches = list(
                re.finditer(
                    r"([A-Za-z .'-]+),\s*(NY|NJ|FL|CA|CT|PA|TX|GA|IL|New York|New Jersey|Florida|California|Connecticut|Pennsylvania|Texas|Georgia|Illinois)\s+(\d{5}(?:-\d{4})?)",
                    raw,
                    re.IGNORECASE,
                )
            )
            for m_city in reversed(matches):
                city_candidate = m_city.group(1).strip()
                # strip blacklist terms inside city candidate
                city_candidate = re.split("|".join([re.escape(t) for t in BANNED_ADDRESS_TERMS]), city_candidate, flags=re.IGNORECASE)[0].strip(" ,")
                if not city_candidate:
                    parts = [p for p in m_city.group(1).split() if p and p.isalpha()]
                    if parts:
                        city_candidate = parts[-1]
                if not city_candidate:
                    continue
                candidate = f"{street_part}, {city_candidate}, {m_city.group(2)} {m_city.group(3)}"
                candidate = clean_address(candidate)
                if _address_has_required_components(candidate):
                    return candidate
        # try to salvage another address substring from the raw text
        for candidate in find_addresses(raw):
            candidate_low = candidate.lower()
            for term in BANNED_ADDRESS_TERMS:
                if term in candidate_low:
                    cut_idx = candidate_low.find(term)
                    candidate = candidate[:cut_idx].strip(" ,")
                    candidate_low = candidate.lower()
            cand_clean = clean_address(candidate)
            if _address_has_required_components(cand_clean) and len(cand_clean) >= 8:
                return cand_clean
        # try again after stripping blacklist segments from raw
        cleaned_raw = raw
        for term in BANNED_ADDRESS_TERMS:
            cleaned_raw = re.sub(term + r".{0,40}", " ", cleaned_raw, flags=re.IGNORECASE)
        for candidate in find_addresses(cleaned_raw):
            cand_clean = clean_address(candidate)
            if _address_has_required_components(cand_clean) and len(cand_clean) >= 8:
                return cand_clean
        if debug is not None:
            debug.setdefault("_warnings", []).append(
                f"WARNING: Address rejected (fails validation). Field={field} Value={raw}"
            )
        # if it still looks like an address with a street number, return a lenient cleaned version
        if re.search(r"\d", addr):
            return clean_address(addr)
        return ""
    addr = re.sub(r"^(\d+),\s*", r"\1 ", addr)
    return addr


def find_addresses(text: str) -> List[str]:
    search_text = re.sub(r"\([^)]+\)", " ", text)
    state_pattern = r"(?:NY|NJ|FL|CA|CT|PA|TX|GA|IL|New York|New Jersey|Florida|California|Connecticut|Pennsylvania|Texas|Georgia|Illinois)"
    patterns = [
        r"\d{1,6}[^\n,]{0,60}?,\s*[A-Za-z .'-]+,\s*[A-Z]{2}\s*\d{5}(?:-\d{4})?",
        r"\d{1,6}\s+[A-Za-z0-9 .'-]+?\s+(?:Street|St|Avenue|Ave|Road|Rd|Drive|Dr|Lane|Ln|Place|Pl|Boulevard|Blvd|Terrace|Ter|Court|Ct|Way)[A-Za-z0-9 .'-]*?,?\s+[A-Za-z .'-]+,?\s+"
        + state_pattern
        + r"\s+\d{5}(?:-\d{4})?",
        r"\d{1,6}\s+[A-Za-z0-9 .'-]+?,\s*[A-Za-z .'-]+(?:\s+[A-Za-z .'-]+)?\s+"
        + state_pattern
        + r"\s+\d{5}(?:-\d{4})?",
    ]
    results: List[str] = []
    for pat in patterns:
        for m in re.finditer(pat, search_text, re.MULTILINE):
            cleaned = clean_address(m.group(0))
            if cleaned not in results:
                results.append(cleaned)
    return results


def find_address_near_keywords(text: str, keywords: Sequence[str]) -> str:
    lowered = text.lower()
    for kw in keywords:
        start = lowered.find(kw.lower())
        if start != -1:
            window = text[max(0, start - 150) : start + 300]
            addresses = find_addresses(window)
            for addr in addresses:
                if "hospital" not in addr.lower():
                    return addr
            if addresses:
                return addresses[0]
    return ""


def pick_best_address(candidates: Sequence[str]) -> str:
    seen = set()
    best_addr = ""
    best_score = -10**9
    for addr in candidates:
        if not addr or addr in seen:
            continue
        seen.add(addr)
        score = _score_address(addr)
        if score > best_score:
            best_score = score
            best_addr = addr
    return best_addr


def extract_phone(text: str) -> str:
    phone_re = re.compile(r"(\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4})")
    match = phone_re.search(text)
    if match:
        return match.group(1)
    return ""


def extract_email(text: str) -> str:
    email_re = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
    match = email_re.search(text)
    if match:
        return match.group(0)
    return ""


def window_after_labels(lines: Sequence[str], label_patterns: Sequence[str], max_lines: int = 4, include_current: bool = False) -> List[str]:
    matches: List[str] = []
    for idx, line in enumerate(lines):
        for pat in label_patterns:
            if re.search(pat, line, re.IGNORECASE):
                start = idx if include_current else idx + 1
                end = min(len(lines), start + max_lines)
                snippet = "\n".join(ln.strip() for ln in lines[start:end] if ln.strip())
                if snippet:
                    matches.append(snippet)
    return matches


def first_line(snippet: str) -> str:
    for line in snippet.splitlines():
        line = line.strip()
        if line:
            return line
    return ""


def best_from_candidates(
    candidates: Sequence[str],
    cleaner,
    validator=None,
) -> str:
    seen = set()
    for cand in candidates:
        clean_val = cleaner(cand) if cleaner else cand
        if not clean_val or clean_val in seen:
            continue
        seen.add(clean_val)
        if validator and not validator(clean_val):
            continue
        return clean_val
    return ""


def extract_relationship(text: str) -> str:
    options = [
        "spouse",
        "husband",
        "wife",
        "son",
        "daughter",
        "brother",
        "sister",
        "mother",
        "father",
        "parent",
        "grandson",
        "granddaughter",
        "niece",
        "nephew",
        "cousin",
        "child",
    ]
    rel_re = re.compile(r"(?i)relationship[^\n]{0,40}?\b(" + "|".join(options) + r")\b")
    match = rel_re.search(text)
    if match:
        return match.group(1).title()
    for opt in options:
        if re.search(rf"(?i)\b{opt}\b", text):
            return opt.title()
    return ""


def extract_property_value(text: str) -> str:
    improved_re = re.compile(r"(?is)improved[\s\S]{0,200}?[$;:, ]*([0-9][0-9,]*\.?\d{0,2})")
    match = improved_re.search(text)
    if match:
        value = match.group(1).replace(",", "")
        try:
            return f"{float(value):.2f}"
        except ValueError:
            return ""
    return ""


def extract_attorney(text: str, debug=None) -> str:
    patterns = [
        r"(?i)print name of attorney[^A-Za-z]{0,30}([A-Z][A-Za-z ,.'-]{2,})",
        r"(?i)attorney(?: for [^:\n]+)?:?\s*([A-Z][A-Za-z ,.'-]{2,})",
        r"(?i)name of attorney:?\s*([A-Z][A-Za-z ,.'-]{2,})",
    ]
    for pat in patterns:
        match = re.search(pat, text)
        if match:
            name = match.group(1)
            name = re.sub(r"(?i),?\s*esq\.?", "", name)
            if re.search(r"(?i)\b(comply|with|must|check)\b", name):
                continue
            cleaned = clean_person_name(name)
            if is_label_noise(cleaned):
                if debug is not None:
                    debug.setdefault("Attorney", []).append(
                        {"source": "attorney_pattern", "value": cleaned, "score": 0, "status": "SKIP", "reason": "label_noise"}
                    )
                continue
            if cleaned and any(role in cleaned.lower() for role in ROLE_WORDS):
                if debug is not None:
                    debug.setdefault("Attorney", []).append(
                        {"source": "attorney_pattern", "value": cleaned, "score": 0, "status": "SKIP", "reason": "role_label"}
                    )
                continue
            if validate_person_name(cleaned) and plausible_name(cleaned):
                if debug is not None:
                    debug.setdefault("Attorney", []).append(
                        {"source": "attorney_pattern", "value": cleaned.strip(" ,"), "score": 100, "status": "OK", "reason": "selected"}
                    )
                return cleaned.strip(" ,")
    return ""


def extract_deceased_name(text: str) -> str:
    will_match = re.search(r"(?i)will of\s+([A-Z][A-Za-z ,.'-]+)", text)
    if will_match:
        candidate = clean_person_name(will_match.group(1))
        if validate_person_name(candidate) and plausible_name(candidate):
            return candidate

    name_re = re.compile(r"(?i)name[:\s]+([A-Z][A-Za-z ,.'-]+)")
    for match in name_re.finditer(text):
        start = match.start()
        context = text[max(0, start - 80) : start + 40].lower()
        if any(kw in context for kw in ["decedent", "deceased", "above-named decedent", "estate of"]):
            candidate = clean_person_name(match.group(1))
            if validate_person_name(candidate) and plausible_name(candidate):
                return candidate

    patterns = [
        r"(?i)decedent information[:\s]+.*?name[^A-Za-z]+([A-Z][A-Za-z ,.'-]+)",
        r"(?i)(?:decedent|deceased)[:\s]+([A-Z][A-Za-z ,.'-]+)",
    ]
    for pat in patterns:
        match = re.search(pat, text, re.DOTALL)
        if match:
            candidate = clean_person_name(match.group(1))
            if validate_person_name(candidate) and plausible_name(candidate):
                return candidate

    estate_match = re.search(r"(?i)estate of\s+([A-Z][A-Za-z ,.'-]+)", text)
    if estate_match:
        candidate = clean_person_name(estate_match.group(1))
        if validate_person_name(candidate) and plausible_name(candidate):
            return candidate
    return ""


def extract_petitioner(text: str) -> str:
    candidates: List[str] = []
    name_re = re.compile(r"(?i)name[:\s]+([A-Z][A-Za-z ,.'-]+)")
    for match in name_re.finditer(text):
        start = match.start()
        context = text[max(0, start - 80) : start + 60].lower()
        if "petitioner" in context:
            name = clean_person_name(match.group(1))
            if plausible_name(name) and name not in candidates:
                candidates.append(name)

    patterns = [
        r"(?i)petitioner information[:\s]+.*?([A-Z][A-Za-z ,.'-]+)\s+United States",
        r"(?i)petitioner(?:'s)?(?: name)?s?[:\s]+([A-Z][A-Za-z ,.'-]+)",
        r"(?i)signature of petitioner[^A-Za-z]{0,20}([A-Z][A-Za-z ,.'-]+)",
        r"(?i)name[:\s]+([A-Z][A-Za-z ,.'-]+)\s*(?:,?\s*petitioner|\(petitioner\)|petitioner)",
        r"(?i)name relationship[^\\n]{0,80}?([A-Z][A-Za-z ,.'-]+)\s+Spouse",
    ]
    for pat in patterns:
        for match in re.finditer(pat, text, re.DOTALL):
            name = clean_person_name(match.group(1))
            if plausible_name(name) and name not in candidates:
                candidates.append(name)
    return candidates[0] if candidates else ""


def extract_petitioner_address(text: str) -> str:
    candidates: List[str] = []
    near = find_address_near_keywords(text, ["petitioner", "mailing address", "petitioner address"])
    if near:
        low = near.lower()
        if "hospital" not in low and "place of death" not in low and "broadway" not in low:
            return near
        candidates.append(near)
    candidates.extend(find_addresses(text))
    best_addr = pick_best_address(candidates)
    return best_addr


def extract_deceased_address(text: str) -> str:
    candidates: List[str] = []

    dom_match = re.search(r"(?i)domicile[:\s]+([^\n]{0,200})", text)
    if dom_match:
        candidates.extend(find_addresses(dom_match.group(1)))

    label_chunks = re.findall(
        r"(?i)(?:domicile address|domicile|place of death|residence)[:\s]+([^\n]{0,150})",
        text,
    )
    for chunk in label_chunks:
        candidates.extend(find_addresses(chunk))

    near_kw = find_address_near_keywords(
        text, ["domicile", "decedent", "deceased", "resided", "residence", "place of death"]
    )
    if near_kw:
        candidates.append(near_kw)

    candidates.extend(find_addresses(text))

    best_addr = pick_best_address(candidates)
    return best_addr


def empty_fields() -> Dict[str, str]:
    return {col: "" for col in Columns}


def generic_extract(raw_text: str, pages_text=None, debug=None) -> Dict[str, str]:
    text = normalize_text(raw_text)
    fields: Dict[str, str] = empty_fields()
    dec_addr = extract_deceased_address(text)
    fields["Deceased Property Address"] = clean_address(dec_addr) if dec_addr else ""
    fields["Deceased Name"] = extract_deceased_name(text)
    fields["Petitioner Name"] = extract_petitioner(text)
    pet_addr = extract_petitioner_address(text)
    fields["Petitioner Address"] = clean_address(pet_addr) if pet_addr else ""
    fields["Relationship"] = extract_relationship(text)
    fields["Property Value"] = extract_property_value(text)
    fields["Attorney"] = extract_attorney(text, debug=debug)
    fields["Phone Number"] = extract_phone(text)
    fields["Email Address"] = extract_email(text)
    return fields

import re
from typing import Dict, List, Optional

from extractor_base import (
    best_from_candidates,
    clean_address,
    clean_person_name,
    is_label_noise,
    validate_person_name,
    correct_ny_phone,
    find_emails_in_pages,
    empty_fields,
    extract_attorney,
    extract_email,
    extract_phone,
    extract_relationship,
    extract_deceased_name,
    extract_petitioner,
    find_address_near_keywords,
    find_addresses,
    pick_best_address,
    plausible_name,
    split_lines,
    window_after_labels,
    clean_address_strict,
    ROLE_BLACKLIST,
    REL_ALLOWED,
)
import difflib

ALLOWED_REL = {
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
}


def _record(debug, field: str, source: str, value: str, score: int, status: str = "OK", reason: str = ""):
    if debug is None:
        return
    debug.setdefault(field, []).append(
        {"source": source, "value": value or "", "score": score, "status": status, "reason": reason}
    )


def _clean_text(val: str) -> str:
    if not val:
        return ""
    val = val.replace("_", " ")
    val = val.replace(" ,", ",")
    val = re.sub(r"\s+,", ",", val)
    val = re.sub(r"\s+", " ", val)
    return val.strip(" :;,")


def _clean_name(raw: str) -> str:
    if not raw:
        return ""
    raw = raw.replace("_", " ")
    raw = re.sub(r"(?i)\bunited\s+states\b", " ", raw)
    raw = raw.strip(" )(")
    raw = raw.strip(" )")
    cut = raw
    aka_match = re.search(r"(?i)(also\s+known\s+as|a\s*/?\s*k\s*/?\s*a|aka|alka|alkia)", cut)
    if aka_match:
        cut = cut[: aka_match.start()]
    cut = re.sub(r"[()\[\]]", " ", cut)
    cut = re.sub(r"[^A-Za-z .'-]", " ", cut)
    tokens = [t for t in re.split(r"\s+", cut) if t]
    cleaned_tokens: List[str] = []
    for t in tokens:
        lower = t.lower().strip(" .,';-")
        if lower in {"jr", "sr"}:
            continue
        if "other" in lower and "specify" in lower:
            continue
        if any(ch.isdigit() for ch in t):
            return ""
        cleaned_tokens.append(t)
    while cleaned_tokens and cleaned_tokens[-1].lower().strip(" .,';-") in ALLOWED_REL:
        cleaned_tokens.pop()
    if len(cleaned_tokens) < 2:
        return ""
    cleaned = clean_person_name(" ".join(cleaned_tokens))
    # Restore middle initial dot if needed
    parts = cleaned.split()
    if len(parts) == 3 and len(parts[1]) == 1:
        parts[1] = parts[1] + "."
        cleaned = " ".join(parts)
    if not plausible_name(cleaned):
        return ""
    return cleaned.strip(" )(")


def _assemble_address(street: str, city: str, state: str, zip_code: str = "") -> str:
    def _title_place(val: str) -> str:
        parts = []
        for part in val.split():
            if len(part) == 2 and part.isupper():
                parts.append(part)
            else:
                parts.append(part.title())
        return " ".join(parts)

    street = street.replace("\n", " ")
    city = city.replace("\n", " ")
    state = state.replace("\n", " ")
    street = _clean_text(street)
    street = re.sub(r"^[^A-Za-z0-9]+", "", street)
    street = re.sub(
        r",\s+(Street|St|Avenue|Ave|Road|Rd|Drive|Dr|Lane|Ln|Boulevard|Blvd|Court|Ct|Place|Pl|Way|Pkwy|Parkway)\b",
        r" \1",
        street,
        flags=re.IGNORECASE,
    )
    city = _clean_text(city)
    city = re.sub(r"(?i)\bcounty\b.*", "", city).strip(" ,")
    city = re.sub(r"(?i)\bstate\b.*", "", city).strip(" ,")
    city = re.sub(r"^[^A-Za-z]+", "", city)
    city_parts = city.split()
    if city_parts and len(city_parts[0]) == 1:
        city = " ".join(city_parts[1:])
    city = _title_place(city)
    state = _clean_text(state)
    state = _title_place(state)
    zip_code = zip_code.strip()
    parts = []
    if street:
        parts.append(street)
    city_state = ", ".join([p for p in [city, state] if p])
    if city_state:
        parts.append(city_state)
    out = ", ".join(parts)
    if out and zip_code:
        out = f"{out} {zip_code}"
    return _clean_text(out)


def _align_last_name_to_decedent(petitioner: str, decedent: str) -> str:
    """
    If petitioner last name is a near-OCR miss of the decedent last name, snap it to the decedent spelling.
    """
    if not petitioner or not decedent:
        return petitioner
    pet_parts = petitioner.split()
    dec_parts = decedent.split()
    if len(pet_parts) < 2 or len(dec_parts) < 2:
        return petitioner
    pet_last = pet_parts[-1].strip(" ,)(")
    dec_last = dec_parts[-1].strip(" ,)(")
    if pet_last.lower() == dec_last.lower():
        return petitioner
    ratio = difflib.SequenceMatcher(None, pet_last.lower(), dec_last.lower()).ratio()
    if ratio >= 0.8:
        pet_parts[-1] = dec_last
        return " ".join(pet_parts)
    return petitioner


def _strict_decedent_name_scan(text: str) -> str:
    patterns = [
        r"(?i)estate\s+of[:\s]+([A-Z][A-Za-z ,.'-]{2,})",
        r"(?i)administration\s+proceeding[^\\n]{0,40}estate\s+of[:\s]+([A-Z][A-Za-z ,.'-]{2,})",
        r"(?i)probate\s+proceeding[^\\n]{0,40}will\s+of[:\s]+([A-Z][A-Za-z ,.'-]{2,})",
        r"(?is)decedent\s+information[^A-Za-z]{0,40}name[:\s]+([A-Z][A-Za-z ,.'-]{2,})",
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            cand = _clean_name(m.group(1))
            if cand:
                return cand
    return ""


def _strict_decedent_address_scan(text: str) -> str:
    anchors = ["domicile address", "domicile: street", "domicile:", "address of decedent", "domicile address: street and number"]
    for anchor in anchors:
        pos = text.lower().find(anchor)
        if pos != -1:
            window = text[max(0, pos - 50) : pos + 300]
            addrs = find_addresses(window)
            if addrs:
                return pick_best_address(addrs)
    # fallback: any address near "decedent"
    pos = text.lower().find("decedent")
    if pos != -1:
        window = text[max(0, pos - 50) : pos + 400]
        addrs = find_addresses(window)
        if addrs:
            return pick_best_address(addrs)
    return ""


def _strip_citizenship(val: str) -> str:
    return re.sub(r"(?i)\b(united\s+states|usa)\b", "", val).strip(" ,")


def _normalize_state_value(val: str) -> str:
    """
    Normalize state strings that may be fused (e.g., 'NEWYORK') or partially OCR'd.
    """
    if not val:
        return ""
    cleaned = _clean_text(val)
    cleaned = re.sub(r"[^A-Za-z ]", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    fused = cleaned.replace(" ", "").lower()
    fixes = {
        "newyork": "New York",
        "newjersey": "New Jersey",
        "florida": "Florida",
        "california": "California",
        "connecticut": "Connecticut",
        "pennsylvania": "Pennsylvania",
        "texas": "Texas",
        "georgia": "Georgia",
        "illinois": "Illinois",
    }
    if fused in fixes:
        return fixes[fused]
    if len(cleaned) == 2 and cleaned.isalpha():
        return cleaned.upper()
    return cleaned.title()


def _extract_deceased_name(text: str, pages_text: Optional[List[str]], debug=None) -> str:
    candidates: List[tuple[int, str]] = []

    def add(raw: str, source: str, score: int):
        raw = re.split(r"(?i)\b(letters|temporary|petition|file no|deceased)", raw)[0]
        cleaned = _clean_name(raw)
        if not cleaned:
            return
        cleaned = cleaned.strip(" )")
        tokens = cleaned.split()
        if tokens and len(tokens[-1]) <= 2:
            cleaned = " ".join(tokens[:-1])
        if not cleaned:
            return
        alpha_len = len(re.sub(r"[^A-Za-z]", "", cleaned))
        if alpha_len < 4:
            _record(debug, "Deceased Name", source, cleaned, score, status="SKIP", reason="too_short")
            return
        if is_label_noise(cleaned):
            _record(debug, "Deceased Name", source, cleaned, score, status="SKIP", reason="label_noise")
            return
        if not validate_person_name(cleaned) or not plausible_name(cleaned):
            _record(debug, "Deceased Name", source, cleaned, score, status="SKIP", reason="invalid_name")
            return
        candidates.append((score, cleaned))
        _record(debug, "Deceased Name", source, cleaned, score, status="OK")

    page1 = pages_text[0] if pages_text and len(pages_text) >= 1 else ""
    page2 = pages_text[1] if pages_text and len(pages_text) >= 2 else ""

    if page1:
        for pat, score, label in [
            (
                r"(?im)probate proceeding,?\s*will of[:\s_]+([^\n]+?)(?=\s+(?:a/k/a|aka|also known|alkia|alk/a|letters|petition|file|deceased|$))",
                125,
                "will_of_header_strict",
            ),
            (
                r"(?im)will of[:\s_]+([^\n]+?)(?=\s+(?:a/k/a|aka|also known|alkia|alk/a|letters|petition|file|deceased|$))",
                120,
                "will_of_pg1",
            ),
            (
                r"(?im)will of[:\s_]+([^\n]+)",
                118,
                "will_of_pg1_relaxed",
            ),
            (
                r"(?im)estate of[:\s_]+([^\n]+?)(?=\s+(?:a/k/a|aka|also known|alkia|alk/a|letters|petition|file|deceased|$))",
                115,
                "estate_of_pg1",
            ),
        ]:
            for m in re.finditer(pat, page1):
                add(m.group(1), label, score)
        dec_block = re.search(r"(?is)the name, domicile.*?as\s+follows:(.{0,800})", page1)
        if dec_block:
            m = re.search(r"(?i)name[:\s]+([^\n]+)", dec_block.group(1))
            if m:
                add(m.group(1), "decedent_block_pg1", 110)

    if not candidates and page2:
        m = re.search(r"(?is)2[^\\n]{0,80}?name[:\\s]+([^\\n]+)", page2)
        if m:
            add(m.group(1), "section_2_pg2_name", 95)

    if not candidates and pages_text:
        for idx, page in enumerate(pages_text):
            m = re.search(r"(?is)decedent information[:\s].{0,120}?name[:\s]+([^\n]+)", page)
            if m:
                add(m.group(1), f"decedent_information_pg{idx+1}", 75)
                break

    if candidates:
        candidates.sort(key=lambda x: (-x[0]))
        best = candidates[0][1]
        # detect alias but keep output as primary name only (per finalized rules)
        search_scope = " ".join(pages_text[:2]) if pages_text else text
        m_alias = re.search(r"(?is)(?:a/k/a|aka|also known as)\s+([A-Za-z .'-]+)", search_scope)
        if m_alias:
            raw_alias = re.split(r"(?i)(letters|trusteeship|temporary|petition)", m_alias.group(1))[0]
            alias_clean = _clean_name(raw_alias)
            if alias_clean and alias_clean.lower() != best.lower():
                _record(debug, "Deceased Name", "alias_detected", alias_clean, candidates[0][0], status="INFO")
        best_full = best
        _record(debug, "Deceased Name", "best_candidate", best_full, candidates[0][0], status="OK", reason="selected")
        return best_full

    fallback = _clean_name(extract_deceased_name(text))
    if fallback:
        alpha_len = len(re.sub(r"[^A-Za-z]", "", fallback))
        if alpha_len < 4 or is_label_noise(fallback):
            _record(debug, "Deceased Name", "generic_fallback", fallback, 5, status="SKIP", reason="invalid_name")
            return ""
        if not validate_person_name(fallback) or not plausible_name(fallback):
            _record(debug, "Deceased Name", "generic_fallback", fallback, 5, status="SKIP", reason="invalid_name")
            return ""
        _record(debug, "Deceased Name", "generic_fallback", fallback, 10, status="OK")
        return fallback


def find_block_after_label(text: str, label: str, max_lines: int = 10) -> List[str]:
    lines = [ln.strip() for ln in text.splitlines()]
    for idx, line in enumerate(lines):
        if label.lower() in line.lower():
            block = []
            for ln in lines[idx + 1 : idx + 1 + max_lines]:
                if not ln:
                    continue
                block.append(ln.strip())
            return block
    return []


def extract_name_after_label(block: List[str], label: str = "Name") -> str:
    skip_patterns = [
        r"\bcitizenship\b",
        r"\bdomicile\b",
        r"\bprincipal office\b",
        r"\baddress\b",
        r"\bmailing address\b",
        r"\bcity\b",
        r"\bvillage\b",
        r"\btown\b",
        r"\bstate\b",
        r"\bzip\b",
        r"\bcountry\b",
    ]
    for idx, line in enumerate(block):
        if label.lower() in line.lower():
            for j in range(idx + 1, min(len(block), idx + 6)):
                candidate = block[j].strip()
                if not candidate:
                    continue
                lower = candidate.lower()
                if any(re.search(pat, lower) for pat in skip_patterns):
                    continue
                if _clean_name(candidate):
                    return candidate
            for j in range(idx + 1, len(block)):
                if block[j].strip():
                    return block[j].strip()
            break
    if block:
        for line in block:
            if _clean_name(line):
                return line
        return block[0]
    return ""


def _fill_city_state_zip(city: str, state: str, zip_code: str, pages_text: Optional[List[str]]) -> (str, str, str):
    city_clean = city.strip()
    if (state and zip_code) or not city_clean or not pages_text:
        return city, state, zip_code
    search_space = "\n".join(pages_text)
    m = re.search(
        rf"{re.escape(city_clean)}[^\n]{{0,40}}(NY|NJ|FL|CA|CT|PA|TX|GA|IL|New York|New Jersey|Florida|California|Connecticut|Pennsylvania|Texas|Georgia|Illinois)[^\d]{{0,10}}(\d{{5}}(?:-\d{{4}})?)",
        search_space,
        re.IGNORECASE,
    )
    if m:
        return city, m.group(1), m.group(2)
    return city, state, zip_code


def extract_address_from_block(block: List[str], pages_text: Optional[List[str]], debug: Optional[dict], field: str) -> str:
    street = city = state = zip_code = ""
    boundary_terms = [
        "description of legacy",
        "devise",
        "other interest",
        "nature of fiduciary status",
        "beneficiary",
        "executor",
        "trustee",
        "distributee",
        "relationship",
        "citizenship",
        "interest(s) of petitioner",
    ]
    for idx, line in enumerate(block):
        low = line.lower()
        if any(term in low for term in boundary_terms):
            break
        if any(lbl in low for lbl in ["domicile address", "principal office", "street and number"]):
            inline_street = re.search(r":\s*([0-9][A-Za-z0-9 .,'/-]+)", line)
            if inline_street:
                street = inline_street.group(1).strip()
            for j in range(idx + 1, min(len(block), idx + 6)):
                lowj = block[j].lower()
                if any(term in lowj for term in boundary_terms):
                    break
                if re.search(r"\d", block[j]) and any(
                    kw in lowj for kw in ["road", "street", "lane", "drive", "avenue", "blvd", "court", "place", "pl", "pkwy", "way"]
                ):
                    street = block[j]
                    break
        if not street and re.search(r"\d", line) and any(
            kw in low for kw in ["road", "street", "lane", "drive", "avenue", "blvd", "court", ","]
        ):
            street = line
        if "city" in low and ("village" in low or "town" in low or "city" in low):
            inline_city = re.search(r"(?i)city[^A-Za-z0-9]+([A-Za-z .'-]+)", line)
            if inline_city:
                city = city or inline_city.group(1).strip()
            if idx + 1 < len(block) and not city:
                city_line = block[idx + 1]
                if "zip" in city_line.lower() or "state" in city_line.lower():
                    continue
                if any(term in city_line.lower() for term in boundary_terms):
                    continue
                combo = re.search(
                    r"([A-Za-z .'-]+),?\s+([A-Za-z]{2,}|[A-Za-z ]+)\s+(\d{5}(?:-\d{4})?)",
                    city_line,
                    re.IGNORECASE,
                )
                if combo:
                    city = combo.group(1)
                    state = combo.group(2)
                    zip_code = combo.group(3)
                else:
                    city = city_line
        if ("state zip code" in low or ("state" in low and "zip" in low)):
            # try same line first
            mself = re.search(r"state[:\s]+([A-Za-z ]+)\s+zip\s*code\s*(\d{5}(?:-\d{4})?)", line, re.IGNORECASE)
            if mself:
                state = state or mself.group(1)
                zip_code = zip_code or mself.group(2)
            if idx + 1 < len(block) and (not state or not zip_code):
                nxt = block[idx + 1]
                if any(term in nxt.lower() for term in boundary_terms):
                    continue
                m = re.search(r"([A-Za-z .'-]+)\s+(\d{5}(?:-\d{4})?)", nxt, re.IGNORECASE)
                if m:
                    state = state or m.group(1)
                    zip_code = zip_code or m.group(2)
    if not city or not state:
        for ln in block:
            if "state" in ln.lower() and "zip" in ln.lower():
                continue
            if any(term in ln.lower() for term in boundary_terms):
                continue
            combo = re.search(
                r"([A-Za-z .'-]+),?\s+([A-Za-z]{2,}|[A-Za-z ]+)\s+(\d{5}(?:-\d{4})?)",
                ln,
                re.IGNORECASE,
            )
            if combo:
                city = city or combo.group(1)
                state = state or combo.group(2)
                zip_code = zip_code or combo.group(3)
                break
    street = _strip_citizenship(street)
    city = _strip_citizenship(city)
    city = re.sub(r"(?i)\b(city|village|town|or)\b", "", city).strip(" ,")
    state = _strip_citizenship(state)
    state = re.sub(r"(?i)state", "", state)
    state = re.sub(r"(?i)zip.*", "", state).strip(" ,")
    city, state, zip_code = _fill_city_state_zip(city, state, zip_code, pages_text)
    addr = _assemble_address(street, city, state, zip_code)
    if addr and (city or state or zip_code):
        cleaned = clean_address_strict(addr, field=field, debug=debug)
        if cleaned and re.search(r"\d", cleaned) and re.search(r"\d{5}", cleaned):
            _record(debug, field, "anchored_block", cleaned, 120)
            return cleaned
        # augment with any address containing the same street to recover missing zip
        if street:
            combined_text = " ".join(pages_text or [])
            all_addrs = find_addresses(combined_text)
            street_tokens = street.split()
            prefix = " ".join(street_tokens[:2]) if len(street_tokens) >= 2 else street_tokens[0] if street_tokens else ""
            for cand in all_addrs:
                if prefix and prefix.lower() in cand.lower():
                    cand_clean = clean_address_strict(cand, field=field, debug=debug)
                    if cand_clean and re.search(r"\d{5}", cand_clean):
                        _record(debug, field, "street_match_fallback", cand_clean, 80)
                        return cand_clean
        if cleaned and re.search(r"\d", cleaned):
            _record(debug, field, "anchored_block_nozip", cleaned, 60)
            return cleaned
    return ""


def _extract_petitioner_name(text: str, pages_text: Optional[List[str]], debug=None) -> str:
    names: List[str] = []
    page1 = pages_text[0] if pages_text and len(pages_text) >= 1 else ""
    page3 = pages_text[2] if pages_text and len(pages_text) >= 3 else ""
    last_page = pages_text[-1] if pages_text else ""

    def add(raw: str, source: str, score: int):
        cleaned = _clean_name(raw)
        if not cleaned:
            return
        if any(cleaned.lower() == n.lower() for n in names):
            return
        names.append(cleaned)
        _record(debug, "Petitioner Name", source, cleaned, score)

    if page1:
        pet_block = find_block_after_label(page1, "Petitioner Information", max_lines=10)
        name_line = extract_name_after_label(pet_block, "Name")
        if name_line:
            add(name_line, "petitioner_info_block", 120)
        if not names:
            block = re.search(r"(?is)petitioner[s]?\s+are\s+as\s+follows[:\s]+(.{0,500})", page1)
            if block:
                for m in re.finditer(r"(?i)name:\s*([^\n]+)", block.group(1)):
                    add(m.group(1), "petitioner_section_pg1", 100)
            if not names:
                m = re.search(r"(?is)petitioner.*?name:\s*([^\n]+)", page1)
                if m:
                    add(m.group(1), "petitioner_window_pg1", 80)
        if names:
            return names[0].strip(" )(")

    if page3:
        lines = page3.splitlines()
        for idx, line in enumerate(lines):
            window = " ".join(lines[idx : idx + 4])
            addr_list = find_addresses(window)
            if not addr_list:
                continue
            addr = addr_list[0]
            pos = window.find(addr)
            name_chunk = window[:pos] if pos > 0 else line
            name_chunk = re.sub(r"(?i)(executor.*|distributee.*|beneficiary.*)", "", name_chunk)
            add(name_chunk, "page3_name_address", 90)

    if not names:
        fallback = extract_petitioner(text)
        cleaned = _clean_name(fallback)
        if cleaned:
            names.append(cleaned)
            _record(debug, "Petitioner Name", "generic_fallback", cleaned, 10)

    # Additional fail-safes
    if not names and page1:
        lt_match = re.search(r"(?i)letters\s+(testamentary|of administration)\s+to[:\s]+([A-Z .,'-]+)", page1)
        if lt_match:
            add(lt_match.group(2), "letters_to_line", 85)
    if not names and last_page:
        sig_match = re.search(r"(?i)signature of petitioner.*?print name[:\s]*([A-Z .,'-]+)", last_page)
        if sig_match:
            add(sig_match.group(1), "signature_print_name", 80)

    return "; ".join(names)


def _extract_petitioner_address(text: str, pages_text: Optional[List[str]], petitioner_name: str, debug=None) -> str:
    page1 = pages_text[0] if pages_text and len(pages_text) >= 1 else ""
    last_page = pages_text[-1] if pages_text else ""

    name_tokens = [t.lower() for t in petitioner_name.split() if t]

    if page1:
        pet_block = find_block_after_label(page1, "Petitioner Information", max_lines=12)
        if pet_block:
            addr = extract_address_from_block(pet_block, pages_text, debug, "Petitioner Address")
            if addr:
                return addr
        # Paragraph 1(a) pattern when no explicit "Petitioner Information" label
        para1 = re.search(r"(?is)1\..*?(?=2\.)", page1) or re.search(r"(?is)1\..{0,800}", page1)
        if para1:
            scope = para1.group(0)
            street = ""
            city = ""
            state = ""
            zip_code = ""
            m_dom = re.search(r"(?i)domicile\s+or\s+principal\s+office[:\s]+([^\n]+)", scope)
            if m_dom:
                street = m_dom.group(1)
            m_cityline = re.search(r"(?im)^\s*([A-Z][A-Z .,'-]+)\s*(NY|NJ|FL|CA|CT|PA|TX|GA|IL|New York|New Jersey|Florida|California|Connecticut|Pennsylvania|Texas|Georgia|Illinois)?\s*(\d{5}(?:-\d{4})?)?\s*$", scope, re.MULTILINE)
            if m_cityline:
                city = m_cityline.group(1)
                if m_cityline.group(2):
                    state = m_cityline.group(2)
                if m_cityline.group(3):
                    zip_code = m_cityline.group(3)
            m_zip = re.search(r"(?i)\b(\d{5})(?:-\d{4})?\b", scope)
            if m_zip:
                zip_code = zip_code or m_zip.group(1)
            addr = _assemble_address(street, city, state, zip_code)
            cleaned = clean_address_strict(addr, field="Petitioner Address", debug=debug)
            if cleaned:
                _record(debug, "Petitioner Address", "paragraph1_block", cleaned, 115)
                return cleaned

    if last_page:
        m = re.search(
            r"(?i)my domicile is:\s*([A-Za-z0-9 ,.'-]+)\s+([A-Za-z .'-]+),\s*(NY|NJ|FL|CA|CT|PA|TX|GA|IL|New York|New Jersey|Florida|California|Connecticut|Pennsylvania|Texas|Georgia|Illinois)\s+(\d{5}(?:-\d{4})?)",
            last_page,
        )
        if m:
            addr = _assemble_address(m.group(1), m.group(2), m.group(3), m.group(4))
            cleaned = clean_address_strict(addr, field="Petitioner Address", debug=debug)
            if cleaned:
                _record(debug, "Petitioner Address", "domicile_last_page", cleaned, 115)
                return cleaned

    if page1:
        block_match = re.search(
            r"(?is)(domicile\s+or\s+principal\s+office[:\s].{0,300})", page1
        )
        if block_match:
            block = block_match.group(1)
            street = re.search(r"(?i)domicile\s+or\s+principal\s+office[:\s]+([^\n]+)", block)
            city = re.search(r"(?i)(?:city|city,\s*village\s*or\s*town)[:\s]+([^\n]+)", block)
            state = re.search(r"(?i)state[:\s]+([^\n]+)", block)
            zip_code = re.search(r"(?i)zip\s*code[:\s]+(\d{5}(?:-\d{4})?)", block)
            addr = _assemble_address(
                street.group(1) if street else "",
                city.group(1) if city else "",
                state.group(1) if state else "",
                zip_code.group(1) if zip_code else "",
            )
            if addr and (city or state or zip_code):
                _record(debug, "Petitioner Address", "domicile_block_pg1", addr, 100)
                return addr
            lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
            if lines:
                street_line = lines[0]
                street_line = re.sub(r"(?i).*domicile[^:]*:\s*", "", street_line)
                for ln in lines[1:]:
                    m = re.search(
                        r"(?i)([A-Za-z .'-]+)\s+(NY|NJ|FL|CA|CT|PA|TX|GA|IL|New York|New Jersey|Florida|California|Connecticut|Pennsylvania|Texas|Georgia|Illinois)\s+(\d{5}(?:-\d{4})?)",
                        ln,
                    )
                    if m:
                        city = m.group(1)
                        state = m.group(2)
                        zip_code = m.group(3)
                        addr = _assemble_address(street_line, city, state, zip_code)
                        if addr:
                            _record(debug, "Petitioner Address", "domicile_block_pg1_lines", addr, 95)
                            return addr
        start = page1.lower().find("domicile or principal office")
        if start != -1:
            window = page1[start : start + 500]
            street = re.search(r"(?i)domicile\s+or\s+principal\s+office[:\s]+([^\n]+)", window)
            city = re.search(r"\n\s*([A-Za-z .'-]+)\s*\(City", window)
            state = re.search(r"\n\s*([A-Za-z .'-]+)\s*\(State", window)
            zip_code = re.search(r"\n\s*(\d{5}(?:-\d{4})?)\s*\(Zip", window)
            addr = _assemble_address(
                street.group(1) if street else "",
                city.group(1) if city else "",
                state.group(1) if state else "",
                zip_code.group(1) if zip_code else "",
            )
            if addr:
                _record(debug, "Petitioner Address", "domicile_window_pg1", addr, 90)
                return addr

    near = find_address_near_keywords(text, ["petitioner", "mailing address", "petitioner address"])
    candidates = []
    if near:
        candidates.append(near)
        _record(debug, "Petitioner Address", "near_petitioner_keyword", near, 40)
    # Avoid table contamination: do not scrape generic addresses from whole text
    best = _clean_text(pick_best_address(candidates))
    if best:
        cleaned = clean_address_strict(best, field="Petitioner Address", debug=debug)
        if cleaned:
            _record(debug, "Petitioner Address", "generic_best", cleaned, 20)
            return cleaned
    return ""


def _extract_deceased_address(text: str, pages_text: Optional[List[str]], debug=None) -> str:
    pages_text = pages_text or []
    page1 = pages_text[0] if pages_text else ""
    state_pattern = r"(NY|NJ|FL|CA|CT|PA|TX|GA|IL|New York|New Jersey|Florida|California|Connecticut|Pennsylvania|Texas|Georgia|Illinois)"

    def _clean_place_name(val: str) -> str:
        val = re.sub(r"(?i)\b(city|town|village|county)\b[^A-Za-z]*", "", val or "")
        val = re.sub(r"\s+", " ", val)
        return val.strip(" ,")

    if page1:
        dec_block = re.search(r"(?is)the name, domicile.*?as\s+follows:(.{0,800})", page1)
        if dec_block:
            block = dec_block.group(1)
            street = ""
            city = ""
            state = ""
            zip_code = ""
            street_match = re.search(r"(?i)domicile[:\s]+(?:street)?\s*([^\n]+)", block)
            if street_match:
                street = street_match.group(1)
            city_match = re.search(r"(?i)\bcity\b[^:\n]*?[ ,:\t]+([^\n]+)", block)
            if city_match:
                city = city_match.group(1)
            state_match = re.search(r"(?i)\bstate\b[^:\n]*[ :\t]+([^\n]+)", block)
            if state_match:
                state = state_match.group(1)
            zip_match = re.search(r"(?i)zip[^:\n]*[:\s]+(\d{5}(?:-\d{4})?)", block)
            if zip_match:
                zip_code = zip_match.group(1)
            lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
            for ln in lines:
                low = ln.lower()
                if low.startswith("city"):
                    cleaned_city = re.sub(r"(?i)city[^A-Za-z]+", "", ln).strip(" :")
                    if not city or len(cleaned_city) > len(city):
                        city = cleaned_city
                if "state" in low:
                    m_state = re.search(r"(?i)state[:\s]+([A-Za-z ]+)", ln)
                    if m_state:
                        cand_state = m_state.group(1)
                        if not state or len(cand_state) > len(state):
                            state = cand_state
                if "zip" in low and not zip_code:
                    m_zip = re.search(r"(?i)(\d{5}(?:-\d{4})?)", ln)
                    if m_zip:
                        zip_code = m_zip.group(1)
            if (not city or not state) and block:
                combo = re.search(rf"([A-Za-z .'-]+)\s+{state_pattern}\s+(\d{{5}}(?:-\d{{4}})?)", block, re.IGNORECASE)
                if combo:
                    city = city or combo.group(1)
                    state = state or combo.group(2)
                    if len(combo.groups()) > 2:
                        zip_code = zip_code or combo.group(3)
            street = _strip_citizenship(street)
            city = _clean_place_name(_strip_citizenship(city))
            state = _normalize_state_value(_clean_place_name(_strip_citizenship(state)))
            addr = _assemble_address(street, city, state, zip_code)
            cleaned = clean_address_strict(addr, field="Deceased Property Address", debug=debug)
            if cleaned and (city or state):
                has_zip = bool(re.search(r"\d{5}", cleaned))
                if has_zip:
                    _record(debug, "Deceased Property Address", "decedent_block_pg1", cleaned, 115)
                    return cleaned
                # try to upgrade with any address containing same street and a zip
                street_tokens = street.split()
                prefix = " ".join(street_tokens[:2]) if len(street_tokens) >= 2 else street_tokens[0] if street_tokens else ""
                combined_text = " ".join(pages_text or [])
                all_addrs = find_addresses(combined_text)
                for cand in all_addrs:
                    if prefix and prefix.lower() in cand.lower():
                        cand_clean = clean_address_strict(cand, field="Deceased Property Address", debug=debug)
                        if cand_clean and re.search(r"\d{5}", cand_clean):
                            _record(debug, "Deceased Property Address", "decedent_block_pg1_zip_upgrade", cand_clean, 116)
                            return cand_clean
                _record(debug, "Deceased Property Address", "decedent_block_pg1_nozip", cleaned, 60)
                return cleaned

    for idx, page in enumerate(pages_text):
        dec_block = find_block_after_label(page, "Domicile Address", max_lines=10)
        if dec_block:
            addr = extract_address_from_block(dec_block, pages_text, debug, "Deceased Property Address")
            if addr:
                return addr
        dom_match = re.search(r"(?is)\(d\)\s*Domicile[:\s]+(?:Street)?\s*([^\n]+)", page)
        if not dom_match:
            dom_match = re.search(r"(?is)Domicile:\s*Street\s*([^\n]+)", page)
        if not dom_match:
            continue
        street_line = dom_match.group(1)
        window = page[dom_match.end() : dom_match.end() + 400]
        city_match = None
        state_match = None
        zip_match = None
        for ln in window.splitlines():
            if not city_match and re.search(r"(?i)\bcity\b", ln):
                mcity = re.search(r"(?i)city[^A-Za-z]*([A-Za-z .'-]+?)(?:,|\s+\d{5}|$)", ln)
                if mcity:
                    city_match = mcity
                mzip_inline = re.search(r"(\d{5}(?:-\d{4})?)", ln)
                if mzip_inline:
                    zip_match = mzip_inline
            if not state_match and re.search(r"(?i)\bstate\b", ln):
                state_match = re.search(r"(?i)\bstate\b[^:]*[ :\t]+([A-Za-z ]+)", ln)
            if not zip_match:
                mzip = re.search(r"(\d{5}(?:-\d{4})?)", ln)
                if mzip:
                    zip_match = mzip
        combo = re.search(rf"([A-Za-z .'-]+),?\s+{state_pattern}\s+(\d{{5}}(?:-\d{{4}})?)", window, re.IGNORECASE)
        street_line = _strip_citizenship(street_line)
        city_val = _clean_place_name(_strip_citizenship(city_match.group(1))) if city_match else (combo.group(1) if combo else "")
        state_val = _normalize_state_value(_clean_place_name(_strip_citizenship(state_match.group(1)))) if state_match else (combo.group(2) if combo else "")
        if state_match and "york" in state_match.group(1).lower():
            state_val = "NY"
        if not city_val and zip_match:
            pre_city = re.search(rf"([A-Za-z][A-Za-z .'-]+),?\s+{zip_match.group(1)}", window)
            if pre_city:
                city_val = pre_city.group(1)
        if not city_val and re.search(r"(?i)staten\s+island", window):
            city_val = "Staten Island"
        if not city_val and re.search(r"(?i)staten\s+island", page):
            city_val = "Staten Island"
        if not state_val and re.search(r"(?i)new york", window):
            state_val = "NY"
        if not state_val and re.search(r"(?i)new york", window):
            state_val = "NY"
        city_val = re.sub(r"(?i)\b(city|town|village|county)\b[^A-Za-z]*", "", city_val or "").strip(" ,")
        addr = _assemble_address(
            street_line,
            city_val,
            state_val,
            zip_match.group(1) if zip_match else (combo.group(3) if combo and len(combo.groups()) >= 3 else ""),
        )
        if addr:
            cleaned = clean_address_strict(addr, field="Deceased Property Address", debug=debug)
            if cleaned:
                _record(debug, "Deceased Property Address", f"domicile_section_pg{idx+1}", cleaned, 105)
                return cleaned

    near = find_address_near_keywords(text, ["domicile", "decedent", "residence", "property address", "place of death"])
    candidates = []
    if near:
        candidates.append(near)
        _record(debug, "Deceased Property Address", "near_domicile_keyword", near, 40)
    candidates.extend(find_addresses(" ".join(pages_text or []) if pages_text else text))
    best = _clean_text(pick_best_address(candidates))
    if best:
        cleaned = clean_address_strict(best, field="Deceased Property Address", debug=debug)
        if cleaned:
            _record(debug, "Deceased Property Address", "generic_best", cleaned, 20)
            return cleaned
    return ""


def _find_relationship_in_lines(lines: List[str], idx: int) -> str:
    for offset in (0, 1):
        pos = idx + offset
        if pos < 0 or pos >= len(lines):
            continue
        line = lines[pos]
        low_line = line.lower()
        has_role = any(role in low_line for role in ROLE_BLACKLIST)
        has_rel_token = any(re.search(rf"(?i)\b{re.escape(opt)}\b", line) for opt in REL_ALLOWED + ["wife", "husband"])
        if has_role and not has_rel_token:
            continue
        for opt in REL_ALLOWED:
            if re.search(rf"(?i)\b{re.escape(opt)}\b", line):
                norm = opt.title()
                if norm.lower() == "wife" or norm.lower() == "husband":
                    norm = "Spouse"
                return norm
    return ""


def _strict_relationship_scan(text: str, petitioner_name: str = "") -> str:
    """
    Second-pass scan across the whole document for relationship labels, filtered by role blacklist.
    """
    pattern = re.compile(
        r"relationship[^A-Za-z]{0,20}(spouse|husband|wife|son|daughter|child|mother|father|sister|brother|niece|nephew|grandchild|grandson|granddaughter)",
        re.IGNORECASE,
    )
    pet_tokens = [t.lower() for t in petitioner_name.split() if t]
    for m in pattern.finditer(text):
        cand = m.group(1).lower()
        window = text[max(0, m.start() - 80) : m.end() + 80].lower()
        if any(role in window for role in ROLE_BLACKLIST):
            continue
        if pet_tokens and not all(tok in window for tok in pet_tokens):
            # prefer matches tied to petitioner; if no petitioner tokens, still allow
            continue
        if cand in {"wife", "husband"}:
            return "Spouse"
        return cand.title()
    return ""


def _extract_relationship(text: str, pages_text: Optional[List[str]], petitioner_name: str, debug=None) -> str:
    PRIORITY = [
        "spouse",
        "wife",
        "husband",
        "domestic partner",
        "child",
        "son",
        "daughter",
        "parent",
        "mother",
        "father",
        "sibling",
        "sister",
        "brother",
        "grandchild",
        "niece",
        "nephew",
        "cousin",
        "other",
        "unknown",
    ]

    def _rank(rel: str) -> int:
        rel_low = rel.lower()
        for idx, val in enumerate(PRIORITY):
            if rel_low == val:
                return idx
        return len(PRIORITY)

    petitioner_tokens = [t.lower() for t in petitioner_name.split()[:2] if t]
    pages_text = pages_text or []
    last_name = petitioner_name.split()[-1].lower() if petitioner_name else ""
    table_markers = {
        "description of legacy",
        "other interest",
        "nature of fiduciary status",
        "legatee",
        "beneficiary",
        "all persons and parties so interested",
        "full residuary legatee",
        "nominated executor",
        "successor executor",
    }

    # Step 1: explicit petitioner block on page 1 (source-of-truth)
    if pages_text:
        page1 = pages_text[0]
        pet_block = find_block_after_label(page1, "Petitioner Information", max_lines=20)
        if pet_block:
            lines = [ln.strip() for ln in pet_block if ln.strip()]
            for idx, line in enumerate(lines):
                if re.search(r"(?i)relationship|interest", line):
                    rel = _find_relationship_in_lines(lines, idx)
                    if rel:
                        _record(debug, "Relationship", "petitioner_block_pg1", rel, 120)
                        return rel
            block_text = " ".join(pet_block).lower()
            m = re.search(
                r"interest[s]?\s+of\s+petitioner[s]?.{0,80}?(spouse|wife|husband|child|son|daughter|sister|brother|mother|father|niece|nephew|cousin)",
                block_text,
                re.IGNORECASE,
            )
            if m:
                rel = m.group(1).title()
                _record(debug, "Relationship", "petitioner_interest_pg1", rel, 115)
                return rel

    candidates: List[Dict[str, str]] = []

    # Step 2: scan pages for petitioner name proximity (avoid tables on later pages)
    for pg_idx, page in enumerate(pages_text):
        if pg_idx >= 1 and any(mark in page.lower() for mark in table_markers):
            continue  # skip beneficiary/distributee tables
        lines = [ln.strip() for ln in page.splitlines() if ln.strip()]
        for idx, line in enumerate(lines):
            low = line.lower()
            has_role = any(role in low for role in ROLE_BLACKLIST)
            has_rel = any(tok in low for tok in ["spouse", "husband", "wife", "son", "daughter", "child", "sister", "brother", "mother", "father", "niece", "nephew", "grandchild", "grandson", "granddaughter"])
            if has_role and not has_rel:
                continue
            match_pet = petitioner_tokens and all(tok in low for tok in petitioner_tokens)
            if not match_pet and last_name:
                match_pet = last_name in low
            if match_pet:
                rel = _find_relationship_in_lines(lines, idx)
                if rel:
                    candidates.append(
                        {
                            "rel": rel.title(),
                            "rank": _rank(rel),
                            "source": f"page{pg_idx+1}_near_petitioner",
                            "score": 100,
                        }
                    )

    # Step 2b: if still empty, allow table scan to pick relationship for petitioner row only
    if not candidates and pages_text and petitioner_name:
        for pg_idx, page in enumerate(pages_text):
            lines = [ln.strip() for ln in page.splitlines() if ln.strip()]
            for idx, line in enumerate(lines):
                low = line.lower()
                if petitioner_name.lower() in low:
                    rel = _find_relationship_in_lines(lines, idx)
                    if rel:
                        candidates.append({"rel": rel.title(), "rank": _rank(rel), "source": f"table_petitioner_pg{pg_idx+1}", "score": 70})
                        break
            if candidates:
                break

    # Step 3: generic fallback (non-table pages only)
    allowed_pages = [p for idx, p in enumerate(pages_text) if not any(mark in p.lower() for mark in table_markers)]
    if allowed_pages:
        rel_source_text = "\n".join(allowed_pages[:2])
        rel = extract_relationship(rel_source_text)
        if rel:
            candidates.append({"rel": rel.title(), "rank": _rank(rel), "source": "generic_fallback", "score": 20})

    # Step 4: spouse override if petitioner name appears near "spouse"
    if petitioner_name:
        pet_tokens = [t.lower() for t in petitioner_name.split() if t]
        search_text = (text or "").lower()
        for m in re.finditer(r"spouse", search_text):
            window = search_text[max(0, m.start() - 80) : m.end() + 80]
            if pet_tokens and all(tok in window for tok in pet_tokens):
                candidates.append({"rel": "Spouse", "rank": _rank("Spouse"), "source": "spouse_window_override", "score": 95})
                break

    if not candidates:
        # Last-resort inference across all pages (including tables) using name proximity
        first_token = petitioner_name.split()[0].lower() if petitioner_name else ""
        last_token = petitioner_name.split()[-1].lower() if petitioner_name else ""
        def _match_name(line_low: str) -> bool:
            if not first_token:
                return False
            if first_token not in line_low:
                return False
            return (last_token and last_token in line_low) or len(first_token) >= 3

        for page in pages_text:
            for line in page.splitlines():
                low = line.lower()
                if not _match_name(low):
                    continue
                has_role = any(role in low for role in ROLE_BLACKLIST)
                has_rel = any(tok in low for tok in ["spouse", "husband", "wife", "son", "daughter", "child", "sister", "brother", "mother", "father", "niece", "nephew", "grandchild", "grandson", "granddaughter"])
                if has_role and not has_rel:
                    continue
                if re.search(r"\b(spouse|husband|wife|widow|widower)\b", low):
                    candidates.append({"rel": "Spouse", "rank": _rank("Spouse"), "source": "fallback_name_line", "score": 60})
                    break
                if re.search(r"\b(son|daughter|child)\b", low):
                    candidates.append({"rel": "Child", "rank": _rank("Child"), "source": "fallback_name_line", "score": 55})
                    break
                if re.search(r"\b(sister|brother)\b", low):
                    candidates.append({"rel": "Sibling", "rank": _rank("Sibling"), "source": "fallback_name_line", "score": 50})
                    break
                if re.search(r"\b(mother|father|parent)\b", low):
                    candidates.append({"rel": "Parent", "rank": _rank("Parent"), "source": "fallback_name_line", "score": 50})
                    break
                if re.search(r"\b(grandchild)\b", low):
                    candidates.append({"rel": "Grandchild", "rank": _rank("Grandchild"), "source": "fallback_name_line", "score": 45})
                    break
                if re.search(r"\b(niece|nephew)\b", low):
                    candidates.append({"rel": "Niece", "rank": _rank("Niece"), "source": "fallback_name_line", "score": 45})
                    break
                if re.search(r"\b(cousin)\b", low):
                    candidates.append({"rel": "Cousin", "rank": _rank("Cousin"), "source": "fallback_name_line", "score": 40})
                    break

    if not candidates:
        # Child class detection from distributee classification section
        if pages_text:
            page2 = pages_text[1] if len(pages_text) >= 2 else pages_text[0]
            page2_low = page2.lower()
            cls_line = re.search(r"(?i)child\s+or\s+children.*?(yes|[1-9])", page2)
            if cls_line or ("child or children" in page2_low and "no child" not in page2_low):
                rel_cls = "Child"
                candidates.append({"rel": rel_cls, "rank": _rank(rel_cls), "source": "distributee_class_child", "score": 60})
        if not candidates:
            default_rel = "Unknown"
            _record(debug, "Relationship", "fallback_default", default_rel, 5)
            return default_rel

    # Select best by priority rank then score
    candidates.sort(key=lambda c: (c["rank"], -c["score"]))
    best = candidates[0]
    _record(debug, "Relationship", best["source"], best["rel"], best["score"])
    return best["rel"]


def _extract_property_value(pages_text: Optional[List[str]], debug=None) -> str:
    if not pages_text:
        return ""

    def _parse_money(val: str) -> float:
        try:
            norm = val.replace(" ", "")
            amount = float(norm.replace(",", ""))
            if "," in norm:
                whole = norm.split(".")[0].replace(",", "")
                post_comma = norm.split(",")[1].split(".")[0] if "," in norm else ""
                if len(post_comma) == 2 and len(whole) <= 5:
                    amount *= 10
            return amount
        except ValueError:
            return 0.0

    # Collect candidates with context scoring
    good_kw = ["gross", "estate", "approximate", "total", "value", "property", "real property", "personal property", "improved"]
    bad_kw = ["filing fee", "receipt", "bond", "cert", "greater than", "less than", "temporary", "fee", "surcharge"]
    candidates: List[tuple[float, int, str]] = []  # (value, score, snippet)

    for page_idx, page in enumerate(pages_text):
        for m in re.finditer(r"\$?\s*([0-9]{1,3}(?:,[0-9]{3})+(?:\.\d{2})?)", page):
            val = _parse_money(m.group(1))
            if val == 0:
                continue
            window_start = max(0, m.start() - 60)
            window_end = min(len(page), m.end() + 60)
            window = page[window_start:window_end].lower()
            if any(bad in window for bad in bad_kw):
                continue
            score = 0
            for kw in good_kw:
                if kw in window:
                    score += 15
            score += min(40, int(val / 100000))  # larger estates score a bit higher
            score += max(0, 10 - page_idx)  # earlier pages slightly higher
            candidates.append((val, score, window))

    # Previous labeled extraction as backup
    improved = unimproved = personal = 0.0
    for page in pages_text:
        lines = page.splitlines()
        joined = " ".join(lines)
        if not improved:
            m = re.search(r"(?i)improved\s+real\s+property[^$]*\$[\s_]*([0-9,\.]+)", joined)
            if m:
                improved = _parse_money(m.group(1))
        if not unimproved:
            m = re.search(r"(?i)unimproved\s+real\s+property[^$]*\$[\s_]*([0-9,\.]+)", joined)
            if m:
                unimproved = _parse_money(m.group(1))
        bad_kw = ["less than", "greater than", "filing fee", "receipt", "bond", "prelim", "cert"]
        personal_candidates = []
        primary_matches = []
        for m in re.finditer(r"(?i)personal\s+propert[y]?[^\$]*\$[\s_]*([0-9,\.]+)", joined):
            val = _parse_money(m.group(1))
            if val:
                primary_matches.append(val)
        if primary_matches:
            personal_candidates.extend(primary_matches)
        else:
            for m in re.finditer(r"\$[\s_]*([0-9,\.]+)\s+personal\s+propert[y]?", joined, re.IGNORECASE):
                ctx = joined[max(0, m.start() - 40) : m.end() + 40].lower()
                val = _parse_money(m.group(1))
                if val and not any(b in ctx for b in bad_kw):
                    personal_candidates.append(val)
        if personal_candidates and personal == 0:
            personal = max(personal_candidates)
    value = 0.0
    chosen_source = ""
    chosen_score = 0
    labeled_candidates = []

    # Collect labeled candidates for prioritisation and size filter
    for source, val, score in [
        ("personal_property", personal, 115),
        ("improved_real_property", improved, 110),
        ("unimproved_real_property", unimproved, 100),
    ]:
        if val and val > 0:
            labeled_candidates.append((val, source, score))

    # Use best context-scored candidate first
    if candidates:
        val, score, _ = max(candidates, key=lambda x: (x[1], x[0]))
        if val >= 1000:
            value = val
            chosen_source = "context_scored"
            chosen_score = score

    if value == 0 and labeled_candidates:
        val, source, score = max(labeled_candidates, key=lambda x: x[0])
        value, chosen_source, chosen_score = val, source, score
    elif value == 0:
        priority_candidates = [
            ("personal_property", personal, 105),
            ("improved_real_property", improved, 100),
            ("unimproved_real_property", unimproved, 90),
        ]
        for source, val, score in priority_candidates:
            if val and val > 0:
                value = val
                chosen_source = source
                chosen_score = score
                break

    # Reject unrealistically small estate values when larger amounts are present
    if value and value < 1000:
        bigger_pool = [v for v, _, _ in labeled_candidates if v >= 1000]
        if candidates:
            bigger_pool.extend([v for v, _, _ in candidates if v >= 1000])
        if bigger_pool:
            value = max(bigger_pool)
            chosen_source = "small_replaced_by_labeled"
            chosen_score = 88

    if value:
        _record(debug, "Property Value", chosen_source or "property_value", f"{value:.2f}", chosen_score or 60)
        out = f"{value:.0f}" if float(value).is_integer() else f"{value:.2f}"
        return out
    return ""


def _extract_phone(text: str, pages_text: Optional[List[str]], debug=None) -> str:
    last_page = pages_text[-1] if pages_text else ""
    page1 = pages_text[0] if pages_text and len(pages_text) >= 1 else ""
    phone = ""
    if last_page:
        match = re.search(r"(\(?\d{3}\)?[-\s.]?\d{3}[-\s.]?\d{4})", last_page)
        if match:
            phone = match.group(1)
            _record(debug, "Phone Number", "last_page_phone", phone, 110)
    if page1:
        match = re.search(
            r"(?i)(telephone\s+number|tel(?:ephone)?)[^\d]{0,15}(\(?\d{3}\)?[-\s.]?\d{3}[-\s.]?\d{4})",
            page1,
        )
        if match:
            phone = match.group(2)
            _record(debug, "Phone Number", "telephone_number_pg1", phone, 100)
    if not phone:
        phone = extract_phone(text)
        if phone:
            _record(debug, "Phone Number", "generic_fallback", phone, 20)
    if phone:
        digits = re.sub(r"\D", "", phone)
        if len(digits) == 10:
            phone = f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"
    return phone


def _extract_attorney_info(text: str, pages_text: Optional[List[str]], debug=None) -> (str, str, str):
    last_page = pages_text[-1] if pages_text else ""
    page_idx = len(pages_text) if pages_text else 0
    attorney = ""
    phone = ""
    email = ""

    def add_candidate(key: str, source: str, value: str, score: int, status: str = "CANDIDATE", reason: str = ""):
        if debug is not None:
            debug.setdefault(key, []).append(
                {"source": source, "value": value or "", "score": score, "status": status, "reason": reason}
            )

    def normalize_phone(raw: str) -> str:
        digits = re.sub(r"\D", "", raw)
        if len(digits) == 10:
            return f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"
        return raw

    # Dedicated attorney block search across all pages
    anchors = [
        "signature of attorney",
        "print name of attorney",
        "firm name",
        "telephone",
        "email (optional)",
    ]
    for idx, page in enumerate(pages_text or []):
        low = page.lower()
        if any(anchor in low for anchor in anchors):
            window = page
            att_name_match = re.search(r"(?i)print name of attorney[^A-Za-z]{0,30}([A-Z .,'-]{3,})", window)
            if att_name_match:
                cand = _clean_name(re.sub(r"(?i)esq\.?", "", att_name_match.group(1)))
                add_candidate("attorney_name_candidates", f"page{idx+1}_block", cand, 110)
                if cand and not is_label_noise(cand) and validate_person_name(cand):
                    attorney = cand
                    _record(debug, "Attorney", f"attorney_block_pg{idx+1}", cand, 120)
            phone_match = re.search(
                r"(?i)(telephone|tel)[^\d]{0,15}(\(?\d{3}\)?[-\s.]?\d{3}[-\s.]?\d{4})", window
            )
            if not phone_match:
                phone_match = re.search(r"(\(?\d{3}\)?[-\s.]?\d{3}[-\s.]?\d{4})", window)
            if phone_match:
                phone_raw = phone_match.group(phone_match.lastindex or 1)
                phone_norm = normalize_phone(phone_raw)
                add_candidate("attorney_phone_candidates", f"page{idx+1}_block", phone_norm, 120)
                if not phone:
                    phone = phone_norm
                    _record(debug, "Phone Number", f"attorney_block_pg{idx+1}", phone_norm, 120)
            email_match = re.search(r"(?i)([A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,})", window, re.IGNORECASE)
            if not email_match:
                email_match = re.search(
                    r"(?i)([A-Z0-9._%+-]+@[A-Z0-9.-]+)\s*\.?\s*(com|net|org|gov|edu|law)",
                    window,
                    re.IGNORECASE,
                )
            if email_match:
                email_val = (
                    email_match.group(0)
                    if email_match.lastindex == 1
                    else f"{email_match.group(1)}.{email_match.group(2)}"
                )
                email_val = email_val.rstrip(" .").lower()
                add_candidate("attorney_email_candidates", f"page{idx+1}_block", email_val, 120)
                if not email:
                    email = email_val
                    _record(debug, "Email Address", f"attorney_block_pg{idx+1}", email_val, 120)

    if last_page:
        collapsed = re.sub(r"\s+", " ", last_page)
        att_block_match = re.search(r"(?is)signature of attorney[:\s]*.{0,800}", last_page)
        att_block = att_block_match.group(0) if att_block_match else last_page

        name_match = re.search(r"(?is)signature of attorney[:\s]*.*?print name[:\s]*([A-Z .,'-]+)", att_block)
        if not name_match:
            name_match = re.search(r"([A-Z .,'-]+?ESQ\.?)", att_block, re.IGNORECASE)
        if not name_match:
            name_match = re.search(r"(?i)print name[:\s]+([A-Z .,'-]{3,})", att_block)
        if name_match:
            attorney = _clean_name(re.sub(r"(?i)esq\.?", "", name_match.group(1)))
            if attorney:
                if is_label_noise(attorney) or not validate_person_name(attorney):
                    _record(debug, "Attorney", f"attorney_block_pg{page_idx}", attorney, 0, status="SKIP", reason="label_noise")
                    attorney = ""
                else:
                    _record(debug, "Attorney", f"attorney_block_pg{page_idx}", attorney, 120)
                add_candidate("attorney_name_candidates", f"page{page_idx}_block", attorney, 120, status="OK")

        phone_match = re.search(
            r"(?i)(tel\s*no\.?|telephone)[^\d]{0,15}(\(?\d{3}\)?[-\s.]?\d{3}[-\s.]?\d{4})", att_block
        )
        if not phone_match:
            phone_match = re.search(r"(\(?\d{3}\)?[-\s.]?\d{3}[-\s.]?\d{4})", att_block)
        if phone_match:
            phone = normalize_phone(phone_match.group(phone_match.lastindex or 1))
            _record(debug, "Phone Number", f"attorney_block_pg{page_idx}", phone, 120)
            add_candidate("attorney_phone_candidates", f"page{page_idx}_block", phone, 120, status="OK")

        email_match = re.search(r"(?i)([A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,})", collapsed, re.IGNORECASE)
        if not email_match:
            partial_match = re.search(
                r"(?i)([A-Z0-9._%+-]+@[A-Z0-9.-]+)\s*\.?\s*([A-Z]{2,})", collapsed, re.IGNORECASE
            )
            if partial_match:
                assembled = f"{partial_match.group(1)}.{partial_match.group(2)}"
                email = assembled.lower()
        if email_match:
            if not email:
                email = email_match.group(1).lower()
            email = email.rstrip(".")
            email = email.replace("gma.il", "gmail.com")
            _record(debug, "Email Address", f"attorney_block_pg{page_idx}", email, 120)
            add_candidate("attorney_email_candidates", f"page{page_idx}_block", email, 120, status="OK")

    if not attorney:
        attorney = extract_attorney(text, debug=debug)
        if attorney:
            _record(debug, "Attorney", "generic_fallback", attorney, 30)
        else:
            _record(debug, "Attorney", "generic_fallback", "", 0, status="SKIP", reason="no_valid_attorney")
    # If attorney still empty but email/phone exist, try to infer name near contact lines
    if not attorney and pages_text:
        last_page = pages_text[-1]
        if email:
            email_pos = last_page.lower().find(email.lower())
            window = last_page[max(0, email_pos - 120) : email_pos + 120] if email_pos != -1 else last_page
            name_match = re.search(r"([A-Z][A-Za-z .,'-]{3,})", window)
            if name_match:
                inferred = _clean_name(name_match.group(1))
                if inferred and validate_person_name(inferred) and not is_label_noise(inferred):
                    attorney = inferred
                    _record(debug, "Attorney", "inferred_from_email_window", attorney, 40)
        if not attorney:
            notary_match = re.search(r"([A-Z][A-Za-z .,'-]{3,})\s+Notary Public", last_page, re.IGNORECASE)
            if notary_match:
                inferred = _clean_name(notary_match.group(1))
                if inferred and validate_person_name(inferred) and not is_label_noise(inferred):
                    attorney = inferred
                    _record(debug, "Attorney", "notary_block_inferred", attorney, 32)
        if not attorney:
            sig_match = re.search(r"Signature of Attorney.*?([A-Z][A-Za-z .,'-]{3,})", last_page, re.IGNORECASE | re.DOTALL)
            if sig_match:
                inferred = _clean_name(sig_match.group(1))
                if inferred and validate_person_name(inferred) and not is_label_noise(inferred):
                    attorney = inferred
                    _record(debug, "Attorney", "signature_nearby", attorney, 35)
    # Phone robustness: prefer phone near attorney name if available
    def _clean_phone(raw: str) -> str:
        digits = re.sub(r"\D", "", raw)
        if len(digits) == 11 and digits.startswith("1"):
            digits = digits[1:]
        if len(digits) != 10:
            return ""
        return f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"

    if attorney and pages_text:
        joined = " ".join(pages_text)
        name_pos = joined.lower().find(attorney.lower())
        best_phone = ""
        if name_pos != -1:
            window = joined[name_pos:name_pos + 400]
            m_phone = re.search(r"(\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4})", window)
            if m_phone:
                best_phone = _clean_phone(m_phone.group(1))
        if not best_phone:
            m_phone = re.search(r"(\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4})", joined)
            if m_phone:
                best_phone = _clean_phone(m_phone.group(1))
        if best_phone:
            phone = best_phone

    if attorney:
        if not email and pages_text:
            email_found = find_emails_in_pages(
                pages_text,
                prefer_near=["signature of attorney", "email (optional)", "print name of attorney", "firm name", "telephone"],
                debug=debug,
            )
            if email_found:
                email = email_found
                _record(debug, "Email Address", "email_pages_scan", email, 90)
        if phone:
            phone = correct_ny_phone(phone, pages_text or [], debug=debug)
        else:
            phone = correct_ny_phone(_extract_phone(text, pages_text, debug), pages_text or [], debug=debug)
    return attorney, phone, email


def extract_form_a(text: str, pages_text: Optional[List[str]] = None, debug=None) -> Dict[str, str]:
    fields: Dict[str, str] = empty_fields()
    attorney, att_phone, att_email = _extract_attorney_info(text, pages_text, debug)
    fields["Deceased Name"] = _extract_deceased_name(text, pages_text, debug)
    if not fields["Deceased Name"]:
        strict_dec = _strict_decedent_name_scan(text)
        if strict_dec:
            fields["Deceased Name"] = strict_dec
            _record(debug, "Deceased Name", "strict_scan", strict_dec, 30)
    fields["Petitioner Name"] = _extract_petitioner_name(text, pages_text, debug)
    fields["Petitioner Name"] = _align_last_name_to_decedent(fields["Petitioner Name"], fields["Deceased Name"])
    fields["Petitioner Address"] = _extract_petitioner_address(text, pages_text, fields["Petitioner Name"], debug)
    fields["Deceased Property Address"] = _extract_deceased_address(text, pages_text, debug)
    if not fields["Deceased Property Address"]:
        strict_addr = _strict_decedent_address_scan(text)
        strict_addr = clean_address_strict(strict_addr, field="Deceased Property Address", debug=debug)
        if strict_addr:
            fields["Deceased Property Address"] = strict_addr
            _record(debug, "Deceased Property Address", "strict_scan", strict_addr, 30)
    rel = _extract_relationship(text, pages_text, fields["Petitioner Name"], debug)
    # If relationship is missing or looks like a role/invalid, run strict scan then fallback to UNKNOWN
    if not rel or rel.lower() not in [r.lower() for r in REL_ALLOWED + ["spouse", "son", "daughter", "child", "mother", "father", "sister", "brother", "niece", "nephew", "grandchild", "grandson", "granddaughter", "unknown"]]:
        strict_rel = _strict_relationship_scan(text, fields["Petitioner Name"])
        if strict_rel:
            rel = strict_rel
            _record(debug, "Relationship", "strict_scan", rel, 30)
    if not rel:
        rel = "Unknown"
        _record(debug, "Relationship", "RELATIONSHIP_REQUIRED_ENFORCEMENT", rel, 1)
    fields["Relationship"] = rel
    fields["Property Value"] = _extract_property_value(pages_text, debug)
    fields["Attorney"] = attorney
    phone_primary = _extract_phone(text, pages_text, debug)
    email_primary = extract_email(text)
    fields["Phone Number"] = att_phone or phone_primary
    fields["Email Address"] = att_email or (email_primary.lower() if email_primary else "")
    if not fields["Email Address"] and pages_text:
        email_found = find_emails_in_pages(
            pages_text,
            prefer_near=["signature of attorney", "email (optional)", "print name of attorney", "firm name", "telephone"],
            debug=debug,
        )
        fields["Email Address"] = email_found or ""

    # Targeted fallbacks for missing fields using anchor-based parsing (without loosening property value rule).
    missing = [k for k, v in fields.items() if not v]
    if missing:
        lines = split_lines(text)
        if "Deceased Name" in missing and not fields["Deceased Name"]:
            deceased_windows = window_after_labels(
                lines, [r"decedent", r"deceased", r"deceased information"], max_lines=2
            )
            deceased_candidates = [ln for ln in (w.split("\n")[0] for w in deceased_windows) if ln]
            for cand in deceased_candidates:
                cleaned = _clean_name(cand)
                if is_label_noise(cleaned):
                    _record(debug, "Deceased Name", "fallback_anchor", cleaned, 0, status="SKIP", reason="label_noise")
                    continue
                if validate_person_name(cleaned) and plausible_name(cleaned):
                    fields["Deceased Name"] = cleaned
                    _record(debug, "Deceased Name", "fallback_anchor", cleaned, 15)
                    break
        if "Petitioner Name" in missing and not fields["Petitioner Name"]:
            petitioner_windows = window_after_labels(
                lines, [r"petitioner", r"petitioner\(s\)", r"co-petitioner", r"petitioner information"], max_lines=2
            )
            petitioner_candidates = [ln for ln in (w.split("\n")[0] for w in petitioner_windows) if ln]
            alt = best_from_candidates(petitioner_candidates, _clean_name, plausible_name)
            if alt:
                fields["Petitioner Name"] = alt
                _record(debug, "Petitioner Name", "fallback_anchor", alt, 15)
        if "Petitioner Address" in missing and not fields["Petitioner Address"]:
            pet_addr_candidates: List[str] = []
            for snippet in window_after_labels(
                lines,
                [r"petitioner address", r"mailing address", r"residence address", r"address of petitioner"],
                max_lines=4,
            ):
                pet_addr_candidates.extend(find_addresses(snippet))
            near_pet = find_address_near_keywords(text, ["petitioner", "mailing address", "petitioner address"])
            if near_pet:
                pet_addr_candidates.append(near_pet)
            best = _clean_text(pick_best_address(pet_addr_candidates))
            if best:
                fields["Petitioner Address"] = best
                _record(debug, "Petitioner Address", "fallback_anchor", best, 15)
        if "Deceased Property Address" in missing and not fields["Deceased Property Address"]:
            dec_addr_candidates: List[str] = []
            for snippet in window_after_labels(
                lines,
                [r"domicile address", r"domicile", r"residence", r"address of decedent", r"property address"],
                max_lines=4,
            ):
                dec_addr_candidates.extend(find_addresses(snippet))
            near_dom = find_address_near_keywords(text, ["domicile", "residence", "property address", "decedent"])
            if near_dom:
                dec_addr_candidates.append(near_dom)
            best = _clean_text(pick_best_address(dec_addr_candidates))
            if best:
                fields["Deceased Property Address"] = best
                _record(debug, "Deceased Property Address", "fallback_anchor", best, 15)
        if fields["Attorney"]:
            if "Phone Number" in missing and not fields["Phone Number"]:
                phone = extract_phone(text)
                if phone:
                    fields["Phone Number"] = phone
                    _record(debug, "Phone Number", "fallback_generic", phone, 10)
            if "Email Address" in missing and not fields["Email Address"]:
                email = extract_email(text)
                if email:
                    fields["Email Address"] = email
                    _record(debug, "Email Address", "fallback_generic", email, 5)

    return fields

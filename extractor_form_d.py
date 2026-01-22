import re
from typing import Dict, List

from extractor_base import (
    best_from_candidates,
    clean_address,
    clean_person_name,
    empty_fields,
    extract_attorney,
    extract_email,
    extract_phone,
    extract_property_value,
    extract_relationship,
    extract_deceased_name,
    extract_petitioner,
    find_address_near_keywords,
    find_addresses,
    first_line,
    pick_best_address,
    plausible_name,
    split_lines,
    window_after_labels,
)


def _extract_relationship_from_windows(windows: List[str]) -> str:
    rel_pat = re.compile(
        r"(?i)\b(spouse|husband|wife|son|daughter|brother|sister|mother|father|parent|grandson|granddaughter|niece|nephew|cousin|child)\b"
    )
    for snippet in windows:
        match = rel_pat.search(snippet)
        if match:
            return match.group(1).title()
    return ""


def _extract_value_from_windows(windows: List[str]) -> str:
    val_pat = re.compile(r"\$?\s*([0-9][0-9,]*\.?\d{0,2})")
    for snippet in windows:
        match = val_pat.search(snippet)
        if match:
            raw = match.group(1).replace(",", "")
            try:
                return f"{float(raw):.2f}"
            except ValueError:
                continue
    return ""


def extract_form_d(text: str, pages_text=None, debug=None) -> Dict[str, str]:
    lines = split_lines(text)
    fields: Dict[str, str] = empty_fields()

    deceased_windows = window_after_labels(
        lines, [r"decedent", r"deceased", r"small estate of", r"voluntary administration of"], max_lines=3
    )
    deceased_candidates = [first_line(snippet) for snippet in deceased_windows]
    fields["Deceased Name"] = best_from_candidates(deceased_candidates, clean_person_name, plausible_name)
    if not fields["Deceased Name"]:
        fields["Deceased Name"] = extract_deceased_name(text)

    petitioner_windows = window_after_labels(
        lines,
        [r"voluntary administrator", r"petitioner", r"informant", r"applicant"],
        max_lines=3,
    )
    petitioner_candidates = [first_line(snippet) for snippet in petitioner_windows]
    fields["Petitioner Name"] = best_from_candidates(petitioner_candidates, clean_person_name, plausible_name)
    if not fields["Petitioner Name"]:
        fields["Petitioner Name"] = extract_petitioner(text)

    dec_addr_candidates: List[str] = []
    for snippet in window_after_labels(
        lines,
        [r"domicile", r"resided at", r"address of decedent", r"decedent address", r"property location"],
        max_lines=4,
    ):
        dec_addr_candidates.extend(find_addresses(snippet))
    near_dom = find_address_near_keywords(text, ["domicile", "resided", "property location", "decedent"])
    if near_dom:
        dec_addr_candidates.append(near_dom)
    fields["Deceased Property Address"] = clean_address(pick_best_address(dec_addr_candidates)) if dec_addr_candidates else ""

    pet_addr_candidates: List[str] = []
    for snippet in window_after_labels(
        lines,
        [r"mailing address", r"address of voluntary administrator", r"residence address", r"petitioner address"],
        max_lines=4,
    ):
        pet_addr_candidates.extend(find_addresses(snippet))
    near_pet = find_address_near_keywords(text, ["voluntary administrator", "petitioner address", "mailing address"])
    if near_pet:
        pet_addr_candidates.append(near_pet)
    fields["Petitioner Address"] = clean_address(pick_best_address(pet_addr_candidates)) if pet_addr_candidates else ""

    rel_windows = window_after_labels(lines, [r"relationship to decedent", r"relationship"], max_lines=2, include_current=True)
    fields["Relationship"] = _extract_relationship_from_windows(rel_windows) or extract_relationship(text)

    value_windows = window_after_labels(lines, [r"improved real property", r"value of property", r"gross value"], max_lines=3)
    fields["Property Value"] = _extract_value_from_windows(value_windows) or extract_property_value(text)

    atty_windows = window_after_labels(lines, [r"attorney", r"counsel", r"law firm"], max_lines=2, include_current=True)
    atty_candidates = [first_line(snippet) for snippet in atty_windows]
    fields["Attorney"] = best_from_candidates(atty_candidates, clean_person_name, plausible_name) or extract_attorney(text, debug=debug)

    fields["Phone Number"] = extract_phone(text)
    fields["Email Address"] = extract_email(text)

    return fields

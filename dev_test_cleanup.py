import sys
import re

from extractor import Columns
from main import process_pdf


def assert_clean_address(addr: str, label: str) -> bool:
    bad = any(tok in addr.lower() for tok in ["richmond", "state:"])
    if bad:
        print(f"[FAIL] {label} contains unwanted tokens: {addr}")
        return False
    if re.search(r"(\d{5}).*\\1", addr):
        print(f"[FAIL] {label} has duplicated ZIP: {addr}")
        return False
    return True


def assert_email_fixed(email: str, expected_domain: str, label: str) -> bool:
    if expected_domain.lower() not in email.lower():
        print(f"[FAIL] {label} expected domain {expected_domain}, got {email}")
        return False
    return True


def assert_phone(phone: str, label: str) -> bool:
    if phone and not re.fullmatch(r"\d{3}-\d{3}-\d{4}", phone):
        print(f"[FAIL] {label} invalid phone format: {phone}")
        return False
    return True


def assert_numeric(value: str, label: str) -> bool:
    if value and not re.fullmatch(r"\d+", value):
        print(f"[FAIL] {label} not numeric: {value}")
        return False
    return True


def main():
    ok = True

    # Multi-case PDF: check first case address cleanup
    multi_results = process_pdf("20260118_SURROGATE’S COURT OF THE STATE OF NEW YORK COUNTY OF RICHMOND.pdf", 200, 300)
    first_case = multi_results[0]["row"]
    addr = dict(zip(Columns, first_case))["Petitioner Address"]
    ok &= assert_clean_address(addr, "Case1 Petitioner Address")

    # Staten Island sample: email normalization
    staten_results = process_pdf("20260118_STATEN ISLAND (1).pdf", 200, 300)
    staten_row = staten_results[0]["row"]
    email = dict(zip(Columns, staten_row))["Email Address"]
    ok &= assert_email_fixed(email, "gmail.com", "Staten Island email")
    ok &= assert_phone(dict(zip(Columns, staten_row))["Phone Number"], "Staten Island phone")
    ok &= assert_numeric(dict(zip(Columns, staten_row))["Property Value"], "Staten Island property")

    # Belleview duplication check
    admin_results = process_pdf("20260118_CAROLYN RUBIO DIAZ.pdf", 200, 300)
    admin_row = dict(zip(Columns, admin_results[0]["row"]))
    ok &= assert_clean_address(admin_row["Petitioner Address"], "Belleview petitioner address")
    ok &= assert_numeric(admin_row["Property Value"], "Belleview property")

    if ok:
        print("All cleanup checks passed.")
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()

import argparse
import sys

from dev_test_samples import process_pdf


def main():
    parser = argparse.ArgumentParser(description="Regression check for 20260118_STATEN ISLAND (1).pdf")
    parser.add_argument("--pdf", default="20260118_STATEN ISLAND (1).pdf", help="PDF path")
    args = parser.parse_args()

    expected = {
        "Deceased Property Address": "165 Nancy Lane, Staten Island, New York 10307",
        "Deceased Name": "Annette Martinelli",
        "Petitioner Name": "Midgie A. Fazio",
        "Petitioner Address": "170 Nancy Lane, Staten Island, New York 10307",
        "Relationship": "Daughter",
        "Property Value": "800000",
        "Attorney": "Terence M. Higgins",
        "Phone Number": "516-365-6414",
        "Email Address": "tmhigginsattorney@gmail.com",
    }

    result = process_pdf(args.pdf, min_text_length=200, ocr_dpi=300)
    fields = result["fields"]

    def check(field, contains=False):
        actual = fields.get(field, "")
        exp = expected[field]
        ok = exp.lower() in actual.lower() if contains else actual.lower() == exp.lower()
        if not ok:
            print(f"[FAIL] {field}: expected '{exp}' got '{actual}'")
            return False
        print(f"[OK] {field}: {actual}")
        return True

    status = [
        check("Deceased Name"),
        check("Petitioner Name"),
        check("Relationship"),
        check("Attorney"),
        check("Phone Number"),
        check("Email Address"),
        check("Property Value"),
        check("Deceased Property Address", contains=True),
        check("Petitioner Address", contains=True),
    ]

    if not all(status):
        sys.exit(1)
    print("All assertions passed.")


if __name__ == "__main__":
    main()

import unittest

from extractor_base import clean_address_strict
from extractor_form_a import _extract_relationship, extract_form_a
from extractor_base import normalize_text


class AddressRelationshipTests(unittest.TestCase):
    def test_beneficiary_address_stripped(self):
        raw = "1311 Ventura Drive, beneficiary of residuary estate Ole . Y Lakewood, New Jersey 08701"
        cleaned = clean_address_strict(raw, field="Petitioner Address")
        self.assertEqual(cleaned, "1311 Ventura Drive, Lakewood, NJ 08701")

    def test_relationship_table_ignored(self):
        # Table page with child but no petitioner relationship
        page1 = "SURROGATE'S COURT\nPetitioner Information:\nName: John Doe\n"
        page3 = "Name and Relationship | Domicile Address | Description of Legacy\nJane Smith Child 123 Road, City, NY 12345 Beneficiary\n"
        rel = _extract_relationship(normalize_text(page1 + "\n" + page3), [page1, page3], "John Doe", debug={})
        self.assertEqual(rel, "Unknown")

    def test_walter_scott_spouse(self):
        page1 = """
SURROGATE'S COURT OF THE STATE OF NEW YORK
PETITION FOR PROBATE
Petitioner Information:
Name: Lillie Ann Scott
Domicile or Principal Office: 16 Ada Drive
City, Village or Town Staten Island
State New York Zip Code 10314
Interest(s) of Petitioner(s): Executor (s) named in decedent's Will
Interest(s) of Petitioner(s)... Distributee of decedent (state relationship): Spouse
"""
        page2 = """
Decedent Information:
Name: Walter Scott
Domicile Address: Street and Number 57 Broad Street
City, Village or Town Staten Island
State New York Zip Code 10301
"""
        pages = [normalize_text(page1), normalize_text(page2)]
        fields = extract_form_a(normalize_text("\n".join(pages)), pages_text=pages, debug={})
        self.assertEqual(fields["Petitioner Address"], "16 Ada Drive, Staten Island, NY 10314")
        self.assertEqual(fields["Relationship"], "Spouse")

    def test_raymond_coles_address_clean(self):
        raw = "1311 Ventura Drive, beneficiary of residuary estate Ole . Y Lakewood, New Jersey 08701"
        cleaned = clean_address_strict(raw, field="Petitioner Address")
        self.assertEqual(cleaned, "1311 Ventura Drive, Lakewood, NJ 08701")


if __name__ == "__main__":
    unittest.main()

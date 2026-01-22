import unittest
from pathlib import Path

from main import process_pdf
from extractor import Columns


class BleedGuardTest(unittest.TestCase):
    def test_no_bleed_between_probate_and_admin(self):
        base = Path(__file__).resolve().parent
        probate_pdf = base / "finalAttached/2025-1463_PROBATE PETITION.pdf"
        admin_pdf = base / "pdf/2026-8_ADMINISTRATION PETITION.pdf"
        prev = {"names": set()}

        probate_res = process_pdf(str(probate_pdf), min_text_length=200, ocr_dpi=300, prev_seen=prev)[0]
        admin_res = process_pdf(str(admin_pdf), min_text_length=200, ocr_dpi=300, prev_seen=prev)[0]

        probate_row = {Columns[i]: probate_res["row"][i] for i in range(len(Columns))}
        admin_row = {Columns[i]: admin_res["row"][i] for i in range(len(Columns))}

        # Expected admin values (Patricia Rubio case)
        self.assertEqual(admin_row["Deceased Name"], "Patricia Rubio")
        self.assertEqual(admin_row["Petitioner Name"], "Carolyn Rubio Diaz")
        self.assertEqual(admin_row["Relationship"], "Sister")
        self.assertEqual(admin_row["Property Value"], "175000")
        self.assertEqual(admin_row["Attorney"], "Grace V")
        self.assertEqual(admin_row["Email Address"], "grace@gracemlawoffice.com")
        self.assertEqual(admin_row["Phone Number"], "718-983-8000")

        # Bleed guard: admin record must not reuse probate names
        self.assertNotEqual(admin_row["Deceased Name"], probate_row["Deceased Name"])
        self.assertNotEqual(admin_row["Petitioner Name"], probate_row["Petitioner Name"])

        # form type tags
        self.assertEqual(admin_res.get("form_type"), "FORM_ADMIN")
        self.assertEqual(probate_res.get("form_type"), "FORM_A")


if __name__ == "__main__":
    unittest.main()

import os
import unittest

from main import process_pdf
from extractor import Columns


PDF_PATH = os.path.join("pdf", "2025-1463_PROBATE PETITION.pdf")


@unittest.skipUnless(os.path.exists(PDF_PATH), "Fixture PDF missing")
class ProbateFazioTest(unittest.TestCase):
    def test_attorney_phone_email(self):
        results = process_pdf(PDF_PATH, min_text_length=200, ocr_dpi=300)
        self.assertGreaterEqual(len(results), 1)
        row = results[0]["row"]
        row_map = {Columns[i]: row[i] for i in range(len(Columns))}

        self.assertEqual(row_map["Deceased Name"], "Annette Martinelli")
        self.assertEqual(row_map["Petitioner Name"], "Midgie A. Fazio")
        self.assertIn("Nancy Lane", row_map["Deceased Property Address"])
        self.assertEqual(row_map["Attorney"], "Terence M Higgins")
        self.assertEqual(row_map["Phone Number"], "516-365-6414")
        self.assertEqual(row_map["Email Address"], "tmhigginsattorney@gmail.com")


if __name__ == "__main__":
    unittest.main()

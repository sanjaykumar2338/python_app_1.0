import os
import unittest

from main import process_pdf
from extractor import Columns


PDF_PATH = os.path.join("pdf", "2025-1166___PROBATE PETITION.pdf")


@unittest.skipUnless(os.path.exists(PDF_PATH), "Fixture PDF missing")
class ProbateBobbeTest(unittest.TestCase):
    def test_bobbe_butler_fields(self):
        results = process_pdf(PDF_PATH, min_text_length=200, ocr_dpi=300)
        self.assertGreaterEqual(len(results), 1)
        row = results[0]["row"]
        row_map = {Columns[i]: row[i] for i in range(len(Columns))}

        self.assertEqual(row_map["Deceased Name"], "Bobbe Butler")
        self.assertIn("57 BROAD STREET", row_map["Deceased Property Address"])
        self.assertEqual(row_map["Petitioner Name"], "Alex Butler")
        self.assertEqual(row_map["Petitioner Address"], "11711 WALL STREET, APT 2302, San Antonio, TX 78230")
        self.assertEqual(row_map["Relationship"], "Son")
        self.assertEqual(row_map["Property Value"], "250000")
        self.assertEqual(row_map["Attorney"], "")
        self.assertEqual(row_map["Phone Number"], "")
        self.assertEqual(row_map["Email Address"], "")


if __name__ == "__main__":
    unittest.main()

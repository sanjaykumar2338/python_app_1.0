import os
import unittest

from main import process_pdf

PDF_DIR = os.path.join(os.path.dirname(__file__), "..", "pdf")


def _first_row(pdf_name: str):
    path = os.path.join(PDF_DIR, pdf_name)
    if not os.path.exists(path):
        raise unittest.SkipTest(f"{pdf_name} not present")
    result = process_pdf(path, min_text_length=200, ocr_dpi=300)
    return result[0]["row"]


class RegressionExtractionTests(unittest.TestCase):
    def test_fern_curry_email_and_value(self):
        row = _first_row("2025-1461_PROBATE PETITION.pdf")
        self.assertEqual(row[8], "jmontello@komlawfirm.com")
        self.assertTrue(row[6])
        self.assertFalse(row[6].strip().endswith((" A", " B", " C", " D", " E")))
        self.assertTrue(row[5].isdigit() and int(row[5]) >= 1000)

    def test_donald_greco_value_present(self):
        row = _first_row("2026-19_PROBATE PETITION.pdf")
        self.assertTrue(row[5].isdigit())
        self.assertGreaterEqual(int(row[5]), 1000)

    def test_patricia_rubio_value_not_zip(self):
        row = _first_row("2026-8_ADMINISTRATION PETITION.pdf")
        self.assertNotEqual(row[5], "10301")
        self.assertTrue(row[5].isdigit() and int(row[5]) >= 1000)

    def test_email_trim_no_suffix(self):
        row = _first_row("2026-16_PROBATE PETITION.pdf")
        self.assertEqual(row[8], "christina@lenzalawfirm.com")

    def test_petitioner_name_fallback_walter_scott(self):
        row = _first_row("2026-10_PROBATE PETITION.pdf")
        self.assertTrue(row[2])
        self.assertEqual(row[2], "Lillie Ann Scott")

    def test_phone_fallback_attorney_higgins(self):
        row = _first_row("2025-1463_PROBATE PETITION.pdf")
        self.assertEqual(row[7], "516-365-6414")


if __name__ == "__main__":
    unittest.main()

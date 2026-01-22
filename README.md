# Probate PDF → Google Sheet + CSV Extractor

Batch reads probate/administration petition PDFs, extracts key fields, writes them to a CSV (columns A–I) and optionally appends the same rows to a Google Sheet. Handles text PDFs first and falls back to OCR for scans.

## Prerequisites
- Python 3.9+
- Tesseract OCR installed and on PATH  
  - macOS: `brew install tesseract`  
  - Windows (admin PowerShell): `choco install tesseract`  
  - Debian/Ubuntu: `sudo apt-get install tesseract-ocr`
- Google service account JSON with Sheets API enabled, and the target sheet shared with the service email.

## Setup
```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### Google service account setup
1) In Google Cloud Console, create a project and enable the **Google Sheets API**.  
2) Create a **Service Account** and generate a **JSON key**; download it (pass its path to `--creds`).  
3) Copy the service account email and **share the target Google Sheet** with it (edit access).  
4) Use the Sheet ID from the sheet URL for `--sheet_id`. Use the tab name for `--worksheet` (omit to use the first tab).

## Usage
```bash
python main.py \
  --pdf_dir "./pdfs" \
  --out_csv "output.csv" \
  --sheet_id "<google-sheet-id>" \
  --worksheet "Probate Information" \
  --creds "service_account.json"

# Debug a single PDF (saves per-page OCR/text to debug/<name>/page_#.txt)
python main.py --debug_pdf "./pdfs/sample.pdf"

# Dev test harness (prints fields and writes output_test.csv)
python dev_test_samples.py --pdf "docs/*.pdf"
```

Flags:
- `--dry_run` to skip Google Sheet writes.
- `--min_text_length` (default 200) controls when OCR kicks in.
- `--ocr_dpi` (default 300) controls OCR render resolution.
- `--log_path` (default `run_log.json`) collects per-file status, missing fields, and any errors.
- `--sheet_link` can be used instead of `--sheet_id` (ID is parsed from the URL).
- `--tesseract_cmd` lets you point to a custom tesseract executable if it’s not on PATH.

## Columns (CSV + Sheet order)
1. Deceased Property Address  
2. Deceased Name  
3. Petitioner Name  
4. Petitioner Address  
5. Relationship  
6. Property Value  
7. Attorney  
8. Phone Number  
9. Email Address  

## How it works
1. Extract text layer with PyMuPDF; if normalized text is shorter than `--min_text_length`, re-run with OCR (Pillow + pytesseract at `--ocr_dpi`).
2. Detect form type (FORM_A–FORM_D) via keyword scoring; write `form_type`, `confidence_score`, and `matched_markers` into `run_log.json`.
3. Run form-specific, anchor-based parsing (labels like DECEASED / PETITIONER / ADDRESS / RELATIONSHIP / IMPROVED REAL PROPERTY) with AKA stripping, address normalization, phone/email regex, and improved-property value checks. Unknown forms fall back to the generic extractor.
4. Append to CSV, append to Google Sheet (unless `--dry_run`), write `run_log.json`. Headers are enforced in A1:I1 with light-blue styling; row 1 is frozen; no data is written beyond column I.

## Testing
- Place the four client PDFs in `tests/fixtures/` and run `tests/run_fixtures.sh` (or `python main.py --pdf_dir tests/fixtures --out_csv tests/out.csv --dry_run`).
- After running, check:
  - `tests/out.csv` (or your chosen `--out_csv`) has 9 columns in the order above and one row per PDF.
  - `run_log.json` lists each file with `extraction_method`, `form_type`, `confidence_score`, `matched_markers`, and `missing_fields`.
  - Google Sheet rows append only when not using `--dry_run`, and no headers or data appear beyond column I.

## Known extraction anchors
- Probate (FORM_A): deceased name from “ESTATE OF …” / section 2(a); petitioner from “petitioner are as follows” block; addresses from domicile and petitioner blocks; property value from “Improved real property in New York State”; phone from “Telephone Number.”
- Administration A-1 (FORM_ADMIN): petitioner/decedent info blocks for names and domicile addresses; relationship from “Distributee of decedent” line; property value from Section 3 totals (improved/unimproved then personal property); attorney/phone/email from final signature block (“Print Name of Attorney”, phone/email lines).

## Notes / limits
- If a field is ambiguous or missing, it is left blank and reported in `run_log.json`.
- Deduplication is not enabled; rerunning will append again. Add your own key if needed.
- OCR runs automatically with Tesseract; consider higher `--ocr_dpi` via CLI or external cleanup for very poor scans.

## GUI / Windows EXE
- Run the desktop UI: `python app_gui.py`
- Build a Windows EXE (requires PyInstaller installed): run `build_exe.bat` on Windows. The EXE starts windowed (no console).
- UI features:
  - Select PDF folder, paste Google Sheet link, choose worksheet, set output CSV.
  - Choose whether to append to Google Sheet using a service-account JSON (recommended) or run CSV-only.
  - OCR is automatic (no OCR settings exposed in the UI); logs show when OCR is used.
  - Progress bar, counts (processed/success/failed/OCR), live log, Stop button, and “Open output folder”.
  - Writes `output.csv` and `run_log.json` to the chosen output folder. If Google write isn’t available (most public sheets are read-only), it clearly falls back to CSV-only.

### Windows release packaging (one-folder EXE + support files)
1) On Windows, install dependencies:  
   ```bash
   python -m venv .venv
   .venv\Scripts\activate
   pip install -r requirements.txt
   pip install pyinstaller
   ```
2) Build: `build_exe.bat` (creates `dist\ProbatePDFExtractor\` containing the EXE plus support files).  
3) Ship the entire `dist\ProbatePDFExtractor\` folder (optionally include a README) and ask the client to provide a service_account.json and share their sheet with that service account.
4) OCR: The EXE assumes Tesseract is installed/available on PATH. Optional portable OCR: bundle a portable tesseract executable alongside the EXE folder and set an environment variable before launch, e.g. `set TESSERACT_CMD=C:\path\to\portable\tesseract.exe`. No UI toggle is needed; OCR runs automatically.

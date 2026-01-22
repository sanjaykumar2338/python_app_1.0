Fixtures are not committed. Drop the four client PDFs into `tests/fixtures/` and run:

```
python main.py --pdf_dir tests/fixtures --out_csv tests/out.csv --dry_run
```

The command writes a CSV in the repo root and a `run_log.json` beside it without touching Google Sheets.

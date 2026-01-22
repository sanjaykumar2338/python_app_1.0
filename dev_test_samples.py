import argparse
import glob
import os
from typing import List

import pandas as pd

from extractor import Columns
from main import process_pdf


def main():
    parser = argparse.ArgumentParser(description="Dev test harness for probate PDFs.")
    parser.add_argument("--pdf", required=True, help="PDF file or glob pattern (e.g., docs/*.pdf)")
    parser.add_argument("--out_csv", default="output_test.csv", help="Where to write extracted rows")
    parser.add_argument("--min_text_length", type=int, default=200, help="Threshold before OCR fallback")
    parser.add_argument("--ocr_dpi", type=int, default=300, help="DPI for OCR rendering")
    parser.add_argument("--debug_json", action="store_true", help="Print structured debug data for each case")
    args = parser.parse_args()

    pdf_paths = sorted(glob.glob(args.pdf))
    if not pdf_paths:
        raise SystemExit(f"No PDFs matched pattern: {args.pdf}")

    rows: List[List[str]] = []
    for pdf_path in pdf_paths:
        results = process_pdf(pdf_path, args.min_text_length, args.ocr_dpi)
        for result in results:
            fields = result["row"]
            row_map = {Columns[i]: fields[i] for i in range(len(Columns))}
            rows.append(fields)
            print(f"\n=== {os.path.basename(pdf_path)} (case {result.get('case_id',1)}) ===")
            detection = result.get("detection", {})
            print(
                f"Form: {detection.get('form_type','UNKNOWN')} (conf {detection.get('confidence_score',0):.3f}) | Method: {result.get('method')}"
            )
            for col in Columns:
                print(f"{col}: {row_map.get(col, '')}")
            missing = result.get("missing", [])
            if missing:
                print(f"Missing: {', '.join(missing)}")
            else:
                print("Missing: none")
            if args.debug_json:
                import json

                print("Debug:")
                print(json.dumps(result.get("debug", {}), indent=2))

    pd.DataFrame(rows, columns=Columns).to_csv(args.out_csv, index=False)
    print(f"\nWrote {len(rows)} rows to {args.out_csv}")
    print("Expected for 20260118_732-691-9989 (Telephone Number).pdf:")
    print('  Deceased Property Address: "863 Strafford Avenue, Staten Island, New York"')
    print('  Deceased Name: "Raymond J. Coles"')
    print('  Petitioner Name: "Raymond G. Coles"')
    print('  Petitioner Address: "1311 Ventura Drive, Lakewood, New Jersey 08701"')
    print('  Relationship: "Child"')
    print('  Property Value: "800000.00"')
    print('  Phone Number: "732-691-9989"')
    print('  Attorney/Email: blank acceptable')


if __name__ == "__main__":
    main()

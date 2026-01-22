import argparse
import glob
import json
import os
from pathlib import Path
from datetime import datetime
from typing import Callable, Dict, List, Optional

import csv
import pytesseract

from extractor import Columns, parse_fields, normalize_row, sanitize_row
from ocr_utils import ExtractionCancelled, extract_pdf_text, get_last_extraction_info
from form_detector import FormType
from diagnostics import log_environment
from sheets import (
    REQUIRED_HEADERS,
    append_rows,
    ensure_headers,
    get_or_create_worksheet,
    load_client,
    sheet_link_to_id,
)


def _split_cases(pages_text: List[str]) -> List[List[str]]:
    markers = []
    marker_types = {}
    for idx, page in enumerate(pages_text):
        low = page.lower()
        mtype = None
        if "administration proceeding" in low or "form a-1" in low or "petition for letters of administration" in low:
            mtype = "ADMIN"
        elif "probate proceeding" in low or "form p-1" in low:
            mtype = "PROBATE"
        if mtype is not None:
            marker_types[idx] = mtype
    # build markers only when case type changes
    sorted_idxs = sorted(marker_types.keys())
    last_type = None
    for idx in sorted_idxs:
        mtype = marker_types[idx]
        if last_type is None or mtype != last_type:
            markers.append(idx)
            last_type = mtype
    if not markers or markers[0] != 0:
        markers = [0] + markers
    markers = sorted(set(markers))
    segments = []
    for i, start in enumerate(markers):
        end = markers[i + 1] if i + 1 < len(markers) else len(pages_text)
        if start < end:
            segments.append(pages_text[start:end])
    return segments or [pages_text]


def _simple_form_hint(pages_text: List[str]) -> Optional[FormType]:
    scope = "\n".join(pages_text[:2]).lower()
    if "form p-1" in scope or "petition for probate" in scope or "probate proceeding" in scope:
        return FormType.FORM_A
    if "form a-1" in scope or "petition for letters of administration" in scope or "administration proceeding" in scope:
        return FormType.FORM_ADMIN
    return None


def process_pdf(pdf_path: str, min_text_length: int, ocr_dpi: int, cancel_event=None, prev_seen=None) -> List[dict]:
    text, method, pages_text = extract_pdf_text(
        pdf_path, min_text_length=min_text_length, ocr_dpi=ocr_dpi, cancel_event=cancel_event
    )
    extraction_info = get_last_extraction_info()
    segments = _split_cases(pages_text)
    results = []
    prev_seen = prev_seen if prev_seen is not None else {"names": set()}
    for idx, seg in enumerate(segments):
        seg_text = "\n".join(seg)
        debug_data: Dict = {}
        form_hint = _simple_form_hint(seg)
        pdf_filename = os.path.basename(pdf_path)
        fields, missing, detection = parse_fields(seg_text, pages_text=seg, debug=debug_data, form_hint=form_hint)
        # Final normalization layer for EXE/script parity
        fields = normalize_row(fields, seg_text, pdf_filename, debug_data)
        # Final sanitize guard before CSV write
        fields = sanitize_row(fields)
        missing = [col for col in Columns if not fields.get(col)]
        if debug_data is not None:
            debug_data["_final_normalized"] = fields
            debug_data["_missing_normalized"] = missing
        record_meta: Dict[str, Dict[str, Optional[str]]] = {}
        field_sources: Dict[str, str] = {}
        for key, candidates in debug_data.items():
            if key.startswith("_") or not isinstance(candidates, list):
                continue
            if not candidates:
                continue
            best = max(candidates, key=lambda c: c.get("score", 0))
            field_sources[key] = best.get("source", "")
        for col in Columns:
            record_meta[col] = {"pdf": pdf_filename, "page": None, "anchor": field_sources.get(col, "")}
        warnings: List[str] = []
        status = "OK"
        # BLEED guard: ensure names are not reused from previous PDFs
        for name_key in ["Deceased Name", "Petitioner Name"]:
            val = fields.get(name_key, "")
            if val and val in prev_seen.get("names", set()):
                fields[name_key] = ""
                if name_key not in missing:
                    missing.append(name_key)
                warnings.append(f"BLEED_GUARD_TRIP:{name_key}")
        prev_seen.setdefault("names", set()).update({v for v in [fields.get("Deceased Name", ""), fields.get("Petitioner Name", "")] if v})

        # Runtime assertion: names must appear in current text
        seg_low = seg_text.lower()
        for key in ["Deceased Name", "Petitioner Name"]:
            val = fields.get(key, "")
            if val and val.lower() not in seg_low:
                warnings.append(f"NAME_NOT_IN_PDF:{key}")
                status = "NEEDS_REVIEW"
                fields[key] = ""
                if key not in missing:
                    missing.append(key)

        # Form-type validation
        form_type_label = form_hint.value if form_hint else detection.form_type
        if form_hint and detection.form_type != form_hint:
            warnings.append("FORM_TYPE_CONFLICT")
        if form_type_label == FormType.FORM_ADMIN.value:
            required = ["Deceased Name", "Petitioner Name", "Relationship", "Property Value"]
            missing_required = [f for f in required if not fields.get(f)]
            if missing_required:
                status = "NEEDS_REVIEW"
                warnings.append(f"REQUIRED_MISSING:{','.join(missing_required)}")
        row = [fields[col] for col in Columns]
        results.append(
            {
                "row": row,
                "missing": missing,
                "method": method,
                "extraction_info": extraction_info,
                "pages_text": seg,
                "detection": detection.to_dict(),
                "case_id": idx + 1,
                "field_sources": field_sources,
                "debug": debug_data,
                "record_meta": record_meta,
                "form_type": form_type_label,
                "warnings": warnings,
                "status": status,
                "error": "",
            }
        )
    return results


def _timestamped_out_path(path: str) -> str:
    base, ext = os.path.splitext(path)
    now = datetime.now()
    month = now.strftime("%b").lower()
    year = now.strftime("%Y")
    time_part = now.strftime("%I-%M%p").lower().lstrip("0")
    return f"{base}_{month}_{year}_{time_part}{ext}"


def write_csv(rows: List[List[str]], out_csv: str, columns: List[str]):
    with open(out_csv, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(columns)
        writer.writerows(rows)


def write_log(log_entries: List[dict], log_path: str):
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(log_entries, f, indent=2)


def run_batch(
    pdf_dir: str,
    out_csv: str,
    sheet_cfg: Optional[Dict] = None,
    settings: Optional[Dict] = None,
    on_progress: Optional[Callable[[Dict], None]] = None,
    on_log: Optional[Callable[[str], None]] = None,
    cancel_event=None,
):
    sheet_cfg = sheet_cfg or {}
    settings = settings or {}

    pdf_pattern = "**/*.pdf" if settings.get("recursive") else "*.pdf"
    pdf_paths = sorted(glob.glob(os.path.join(pdf_dir, pdf_pattern), recursive=settings.get("recursive", False)))
    if not pdf_paths:
        raise FileNotFoundError(f"No PDFs found in {pdf_dir}")

    tesseract_cmd = settings.get("tesseract_cmd") or os.environ.get("TESSERACT_CMD") or os.environ.get("TESSERACT_PATH")
    if tesseract_cmd:
        pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
    # parity log
    print(f"exe_mode={'frozen' if getattr(__import__('sys'),'frozen',False) else 'script'} python={__import__('sys').version.split()[0]}")

    log_entries: List[dict] = []
    env_snapshot = {"type": "environment", **log_environment()}
    log_entries.append(env_snapshot)
    if on_log:
        runtime = env_snapshot.get("runtime", {})
        deps = env_snapshot.get("deps", {})
        on_log(
            f"[ENV] exe_mode={runtime.get('exe_mode')} python={runtime.get('python_version')} "
            f"fs_enc={runtime.get('fs_encoding')} locale_enc={runtime.get('preferred_encoding')} "
            f"fitz={deps.get('fitz')} pdfplumber={deps.get('pdfplumber')} pytesseract={deps.get('pytesseract')}"
        )
    rows: List[List[str]] = []
    debug_csv = os.getenv("DEBUG_EXTRACT", "0") == "1"
    columns_out = list(Columns)
    if debug_csv:
        columns_out += ["extraction_mode", "text_len", "pdf_name"]

    stats = {
        "total": len(pdf_paths),
        "processed": 0,
        "success": 0,
        "failed": 0,
        "ocr": 0,
        "cancelled": False,
    }

    ws = None
    sheet_error = ""
    append_enabled = bool(sheet_cfg.get("append", False))

    if append_enabled:
        sheet_id = sheet_cfg.get("sheet_id") or sheet_link_to_id(sheet_cfg.get("sheet_link", ""))
        creds_path = sheet_cfg.get("creds")
        worksheet_name = sheet_cfg.get("worksheet")
        if not (sheet_id and creds_path):
            append_enabled = False
            sheet_error = "Missing sheet ID or credentials; skipping Google append."
            if on_log:
                on_log(f"[WARN] {sheet_error}")
        else:
            try:
                client = load_client(creds_path)
                ws = get_or_create_worksheet(client, sheet_id, worksheet_name)
                ensure_headers(ws, REQUIRED_HEADERS, log_fn=on_log)
            except Exception as exc:  # noqa: BLE001
                append_enabled = False
                sheet_error = f"Failed to init sheet: {exc}"
                if on_log:
                    on_log(f"[WARN] {sheet_error}")

    def report_progress():
        if on_progress:
            on_progress(stats)

    def log(msg: str):
        if on_log:
            on_log(msg)

    report_progress()

    out_csv_final = out_csv
    if os.path.basename(out_csv) == "output.csv":
        out_csv_final = _timestamped_out_path(out_csv)

    bleed_seen = {"names": set()}

    for pdf_path in pdf_paths:
        if cancel_event and hasattr(cancel_event, "is_set") and cancel_event.is_set():
            stats["cancelled"] = True
            log("Cancellation requested. Stopping further processing.")
            break

        file_name = os.path.basename(pdf_path)
        try:
            results = process_pdf(
                pdf_path,
                settings.get("min_text_length", 200),
                settings.get("ocr_dpi", 300),
                cancel_event=cancel_event,
                prev_seen=bleed_seen,
            )
            for result in results:
                log_entry = {
                    "file": file_name,
                    "case_id": result.get("case_id", 1),
                    "extraction_method": result["method"],
                    "extraction_info": result.get("extraction_info", {}),
                    "form_type": "",
                    "confidence_score": 0,
                    "matched_markers": [],
                    "missing_fields": result["missing"],
                    "error": "",
                    "pages_used": len(result.get("pages_text", [])),
                    "field_sources": result.get("field_sources", {}),
                }
                detection = result.get("detection", {}) or {}
                log_entry["form_type"] = detection.get("form_type", "UNKNOWN")
                log_entry["confidence_score"] = detection.get("confidence_score", 0)
                log_entry["matched_markers"] = detection.get("matched_markers", [])
                row_out = list(result["row"])
                if debug_csv:
                    info = result.get("extraction_info", {}) or {}
                    row_out += [
                        info.get("extraction_mode", result.get("method", "")),
                        info.get("text_len", None),
                        file_name,
                    ]
                rows.append(row_out)
                stats["success"] += 1
                if result["method"] in ("OCR", "MIXED"):
                    stats["ocr"] += 1
                if append_enabled and ws:
                    try:
                        append_rows(ws, [result["row"]], REQUIRED_HEADERS)
                    except Exception as exc:  # noqa: BLE001
                        log(f"[WARN] Failed to append {file_name} (case {log_entry['case_id']}) to Google Sheet: {exc}")
                missing_msg = ", ".join(result["missing"]) if result["missing"] else "none"
                form_tag = detection.get("form_type", "UNKNOWN")
                msg_prefix = f"[{result['method']}/{form_tag}/case-{log_entry['case_id']}] {file_name}"
                log(f"{msg_prefix} -> missing: {missing_msg}")
                if form_tag == "UNKNOWN":
                    log(f"[WARN] {file_name} case {log_entry['case_id']} unknown form type; extraction may be incomplete")
                log_entries.append(log_entry)
        except ExtractionCancelled:
            stats["cancelled"] = True
            log("Cancelled during extraction. Stopping.")
            break
        except Exception as exc:  # noqa: BLE001
            stats["failed"] += 1
            log(f"[ERROR] {file_name} -> {exc}")
            log_entries.append(
                {
                    "file": file_name,
                    "case_id": 1,
                    "extraction_method": "",
                    "form_type": "",
                    "confidence_score": 0,
                    "matched_markers": [],
                    "missing_fields": [],
                    "error": str(exc),
                    "pages_used": 0,
                }
            )
        stats["processed"] += 1
        report_progress()

    # Always write CSV so headers exist even if cancelled/failed.
    write_csv(rows, out_csv_final, columns_out)
    log_path = settings.get("log_path") or "run_log.json"
    write_log(log_entries, log_path)

    summary = {
        "stats": stats,
        "log_entries": log_entries,
        "sheet_error": sheet_error,
        "out_csv": out_csv_final,
        "log_path": log_path,
    }
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Probate PDF extractor to Google Sheets + CSV")
    parser.add_argument("--pdf_dir", help="Folder containing PDF files (required unless using --debug_pdf)")
    parser.add_argument("--debug_pdf", help="Debug a single PDF (prints candidates, saves per-page OCR text)")
    parser.add_argument("--out_csv", default="output.csv", help="Output CSV path")
    parser.add_argument("--sheet_id", help="Google Sheet ID")
    parser.add_argument("--sheet_link", help="Google Sheet link (will be parsed for ID)")
    parser.add_argument("--worksheet", help="Worksheet name (defaults to first)")
    parser.add_argument("--creds", help="Path to Google service account JSON")
    parser.add_argument("--no_sheet", action="store_true", help="Skip Google Sheets writes")
    parser.add_argument("--dry_run", action="store_true", help="Skip Google Sheets writes (alias)")
    parser.add_argument("--min_text_length", type=int, default=200, help="Threshold before OCR fallback")
    parser.add_argument("--ocr_dpi", type=int, default=300, help="DPI used for OCR rendering")
    parser.add_argument("--log_path", default="run_log.json", help="Path for per-file log")
    parser.add_argument("--recursive", action="store_true", help="Process PDFs in subfolders")
    parser.add_argument("--tesseract_cmd", help="Path to tesseract executable (if not on PATH)")
    return parser.parse_args()


def run_debug(pdf_path: str, settings: Dict):
    pdf_path = os.path.abspath(pdf_path)
    debug_dir = Path("debug") / Path(pdf_path).stem
    debug_dir.mkdir(parents=True, exist_ok=True)

    text, method, pages_text = extract_pdf_text(
        pdf_path,
        min_text_length=settings.get("min_text_length", 200),
        ocr_dpi=settings.get("ocr_dpi", 300),
    )

    for idx, page_text in enumerate(pages_text):
        out_path = debug_dir / f"page_{idx + 1}.txt"
        out_path.write_text(page_text, encoding="utf-8")

    debug_data: Dict = {}
    fields, missing, detection = parse_fields(text, pages_text=pages_text, debug=debug_data)

    print(f"Debugging {pdf_path}")
    print(f"Detection: {detection.form_type.value} (confidence {detection.confidence:.3f})")
    print(f"Matched markers: {', '.join(detection.matched_markers) if detection.matched_markers else 'none'}")
    print(f"Extraction method: {method}")
    print(f"Saved per-page OCR/text to: {debug_dir}")
    print("\nFields:")
    for col in Columns:
        print(f"- {col}: {fields.get(col, '')}")
        candidates = sorted(debug_data.get(col, []), key=lambda c: (-c.get("score", 0), c.get("source", "")))
        for cand in candidates:
            val = cand.get("value", "")
            score = cand.get("score", 0)
            source = cand.get("source", "")
            print(f"    candidate [{score}] {source}: {val}")
    print(f"\nMissing fields: {', '.join(missing) if missing else 'none'}")


def main():
    args = parse_args()

    if args.debug_pdf:
        settings = {
            "min_text_length": args.min_text_length,
            "ocr_dpi": args.ocr_dpi,
            "tesseract_cmd": args.tesseract_cmd,
        }
        if args.tesseract_cmd:
            pytesseract.pytesseract.tesseract_cmd = args.tesseract_cmd
        run_debug(args.debug_pdf, settings)
        return

    if not args.pdf_dir:
        raise SystemExit("--pdf_dir is required unless --debug_pdf is provided")

    append = not (args.no_sheet or args.dry_run)
    sheet_cfg = {
        "append": append and (args.sheet_id or args.sheet_link),
        "sheet_id": args.sheet_id,
        "sheet_link": args.sheet_link,
        "worksheet": args.worksheet,
        "creds": args.creds,
    }
    settings = {
        "min_text_length": args.min_text_length,
        "ocr_dpi": args.ocr_dpi,
        "log_path": args.log_path,
        "recursive": args.recursive,
        "tesseract_cmd": args.tesseract_cmd,
    }

    summary = run_batch(
        pdf_dir=args.pdf_dir,
        out_csv=args.out_csv,
        sheet_cfg=sheet_cfg,
        settings=settings,
        on_log=print,
    )

    stats = summary["stats"]
    print(
        f"Done. Processed {stats['processed']} of {stats['total']} PDFs "
        f"(success {stats['success']}, failed {stats['failed']}, OCR {stats['ocr']})."
    )
    if summary.get("sheet_error"):
        print(f"Sheet warning: {summary['sheet_error']}")
    print(f"CSV: {summary['out_csv']} | Log: {summary['log_path']}")


if __name__ == "__main__":
    main()

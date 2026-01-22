import re
from typing import List, Optional

import gspread
from google.oauth2 import service_account

REQUIRED_HEADERS = [
    "Deceased Property Address",
    "Deceased Name",
    "Petitioner Name",
    "Petitioner Address",
    "Relationship",
    "Property Value",
    "Attorney",
    "Phone Number",
    "Email Address",
]


SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


def sheet_link_to_id(url: str) -> str:
    """Extract Sheet ID from a full Google Sheet URL."""
    match = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", url)
    return match.group(1) if match else ""


def load_client(creds_path: str) -> gspread.Client:
    creds = service_account.Credentials.from_service_account_file(creds_path, scopes=SCOPES)
    return gspread.authorize(creds)


def get_or_create_worksheet(client: gspread.Client, sheet_id: str, worksheet_name: Optional[str] = None):
    sh = client.open_by_key(sheet_id)
    if worksheet_name:
        try:
            return sh.worksheet(worksheet_name)
        except gspread.WorksheetNotFound:
            return sh.add_worksheet(title=worksheet_name, rows=1000, cols=20)
    return sh.sheet1


def _col_letter(n: int) -> str:
    """Convert 1-based column index to column letter."""
    result = ""
    while n:
        n, rem = divmod(n - 1, 26)
        result = chr(65 + rem) + result
    return result


def ensure_headers(ws, headers: List[str], log_fn=None) -> None:
    """Ensure required headers live in A1:I1 (fixed). Repairs or creates as needed, styles row, freezes row 1."""
    required_norm = {h.strip().lower() for h in headers}
    try:
        row1 = ws.row_values(1)
    except Exception:
        row1 = []

    # Check for stray headers in J1:Z1 and clear if they include any required names
    try:
        extra = ws.get("J1:Z1")
        if extra and any(cell.strip().lower() in required_norm for cell in extra[0] if cell):
            ws.batch_clear(["J1:Z1"])
    except Exception:
        pass

    def _apply_styling():
        try:
            ws.spreadsheet.batch_update(
                {
                    "requests": [
                        {
                            "repeatCell": {
                                "range": {
                                    "sheetId": ws.id,
                                    "startRowIndex": 0,
                                    "endRowIndex": 1,
                                    "startColumnIndex": 0,
                                    "endColumnIndex": len(headers),
                                },
                                "cell": {
                                    "userEnteredFormat": {
                                        "backgroundColor": {
                                            "red": 207 / 255,
                                            "green": 226 / 255,
                                            "blue": 243 / 255,
                                        },
                                        "textFormat": {"bold": True},
                                    }
                                },
                                "fields": "userEnteredFormat(backgroundColor,textFormat)",
                            }
                        },
                        {
                            "updateSheetProperties": {
                                "properties": {"sheetId": ws.id, "gridProperties": {"frozenRowCount": 1}},
                                "fields": "gridProperties.frozenRowCount",
                            }
                        },
                    ]
                }
            )
        except Exception:
            pass

    def _write_headers():
        ws.update("A1:I1", [headers])
        _apply_styling()

    # Empty row check (first 9 cols blank)
    if not row1 or not any(cell.strip() for cell in row1[: len(headers)]):
        _write_headers()
        if log_fn:
            log_fn("Header row created.")
        return

    # Check A1:I1 contents
    try:
        existing_range = ws.get(f"A1:{_col_letter(len(headers))}1")
        existing = existing_range[0] if existing_range else []
    except Exception:
        existing = row1[: len(headers)]

    existing = (existing + [""] * len(headers))[: len(headers)]
    if [e.strip().lower() for e in existing] != [h.lower() for h in headers]:
        _write_headers()
        if log_fn:
            log_fn("Header row repaired to required schema.")
    else:
        if log_fn:
            log_fn("Headers validated: OK")


def append_rows(ws, rows: List[List[str]], required_headers: List[str]):
    def _next_empty_row() -> int:
        try:
            col_a = ws.col_values(1)
        except Exception:
            return 2
        if not col_a:
            return 2
        for idx, val in enumerate(col_a[1:], start=2):
            if not str(val).strip():
                return idx
        return len(col_a) + 1

    cleaned_rows: List[List[str]] = []
    for row in rows:
        out = list(row[: len(required_headers)])
        if len(out) < len(required_headers):
            out += [""] * (len(required_headers) - len(out))
        cleaned_rows.append(out)

    for out in cleaned_rows:
        next_row = _next_empty_row()
        range_name = f"A{next_row}:I{next_row}"
        ws.update(range_name, [out], value_input_option="USER_ENTERED")

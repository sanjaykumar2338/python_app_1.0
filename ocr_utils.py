import io
import os
import threading
from typing import List, Optional, Tuple

import fitz
from PIL import Image, ImageOps
import pytesseract

_last_info = {}


class ExtractionCancelled(Exception):
    """Raised when a cancellation is requested during OCR/text extraction."""


def _simple_normalize(text: str) -> str:
    return " ".join(text.split())


def preprocess_image(image: Image.Image) -> Image.Image:
    gray = ImageOps.grayscale(image)
    return ImageOps.autocontrast(gray)


def _ocr_page(page, pdf_path: str, page_idx: int, dpi: int, cancel_event: Optional["threading.Event"] = None) -> str:
    if cancel_event and cancel_event.is_set():
        raise ExtractionCancelled("Cancelled before OCR page render.")
    matrix = fitz.Matrix(dpi / 72, dpi / 72)
    pix = page.get_pixmap(matrix=matrix)
    img = Image.open(io.BytesIO(pix.tobytes("png")))
    processed = preprocess_image(img)
    if os.getenv("DEBUG_EXTRACT") == "1":
        base = os.path.splitext(os.path.basename(pdf_path))[0]
        dbg_dir = os.path.join("debug_artifacts", base)
        os.makedirs(dbg_dir, exist_ok=True)
        img.save(os.path.join(dbg_dir, f"page_{page_idx+1}_raw.png"))
        processed.save(os.path.join(dbg_dir, f"page_{page_idx+1}_proc.png"))
    if cancel_event and cancel_event.is_set():
        raise ExtractionCancelled("Cancelled before OCR.")
    text = pytesseract.image_to_string(processed)
    if os.getenv("DEBUG_EXTRACT") == "1":
        base = os.path.splitext(os.path.basename(pdf_path))[0]
        dbg_dir = os.path.join("debug_artifacts", base)
        with open(os.path.join(dbg_dir, f"page_{page_idx+1}_ocr.txt"), "w", encoding="utf-8") as f:
            f.write(text)
    return text


def extract_pdf_text(
    pdf_path: str,
    min_text_length: int = 80,
    ocr_dpi: int = 300,
    cancel_event: Optional["threading.Event"] = None,
) -> Tuple[str, str, List[str]]:
    global _last_info
    env_min_text = os.getenv("MIN_TEXT_LEN")
    if env_min_text and env_min_text.isdigit():
        min_text_length = int(env_min_text)
    prefer_text_layer = os.getenv("PREFER_TEXT_LAYER", "0") == "1"
    doc = fitz.open(pdf_path)
    try:
        page_texts = [doc[i].get_text("text") for i in range(len(doc))]
        total_text = " ".join(page_texts)
        total_len = len(_simple_normalize(total_text))

        use_full_ocr = (total_len < min_text_length) and (not prefer_text_layer)

        if use_full_ocr:
            texts = [_ocr_page(doc[i], pdf_path, i, ocr_dpi, cancel_event) for i in range(len(doc))]
            method = "OCR_FALLBACK"
        else:
            texts = []
            used_ocr = False
            for i in range(len(doc)):
                if cancel_event and cancel_event.is_set():
                    raise ExtractionCancelled("Cancelled during text extraction.")
                if len(_simple_normalize(page_texts[i])) < 10:
                    texts.append(_ocr_page(doc[i], pdf_path, i, ocr_dpi, cancel_event))
                    used_ocr = True
                else:
                    texts.append(page_texts[i])
            method = "MIXED" if used_ocr else "TEXT_LAYER"
    finally:
        doc.close()

    _last_info = {
        "pdf": os.path.basename(pdf_path),
        "extraction_mode": method,
        "render_dpi": ocr_dpi,
        "renderer": f"pymupdf {fitz.__doc__[:5] if hasattr(fitz,'__doc__') else ''}".strip(),
        "pages": len(texts),
        "text_len": total_len,
    }
    if os.getenv("DEBUG_EXTRACT") == "1":
        print(f"[EXTRACT_INFO] {_last_info}")
    return "\n".join(texts), method, texts


def get_last_extraction_info() -> dict:
    return _last_info.copy()

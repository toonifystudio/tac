# Minimal OCR helpers: pypdf for text extraction, PyMuPDF + pytesseract for OCR
from __future__ import annotations
import os
import logging
from typing import Dict
from pypdf import PdfReader

LOG = logging.getLogger(__name__)

try:
    import fitz  # PyMuPDF
    from PIL import Image
    import pytesseract
except Exception:
    fitz = None


def extract_text_from_pdf(path: str) -> Dict[int, str]:
    """Extract text from a PDF using pypdf's text extraction. Returns dict page->text."""
    texts = {}
    reader = PdfReader(path)
    for i, page in enumerate(reader.pages):
        try:
            txt = page.extract_text() or ''
        except Exception:
            txt = ''
        texts[i] = txt
    return texts


def is_scanned_pdf(texts: Dict[int, str]) -> bool:
    # If fewer than half of pages have text, treat as scanned
    if not texts:
        return True
    non_empty = sum(1 for t in texts.values() if t and t.strip())
    return non_empty < max(1, len(texts) / 2)


def ocr_pdf(path: str) -> Dict[int, str]:
    """Run OCR on each page and return dict page->text. Requires PyMuPDF + pytesseract."""
    if fitz is None:
        raise RuntimeError("PyMuPDF (fitz) is required for OCR. Install PyMuPDF and pytesseract.")
    doc = fitz.open(path)
    out = {}
    for page_num in range(len(doc)):
        page = doc.load_page(page_num)
        pix = page.get_pixmap(alpha=False)
        img_bytes = pix.tobytes()
        try:
            from io import BytesIO
            im = Image.open(BytesIO(img_bytes))
            txt = pytesseract.image_to_string(im)
        except Exception as e:
            LOG.exception('OCR failed on page %s: %s', page_num, e)
            txt = ''
        out[page_num] = txt
    return out

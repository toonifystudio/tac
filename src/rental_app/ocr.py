import logging
from typing import List, Dict, Any, Optional
from pathlib import Path

import fitz  # PyMuPDF
import pytesseract
from PIL import Image

logger = logging.getLogger(__name__)


def extract_text_from_pdf(path: str) -> Dict[int, str]:
    """Extract text per page from a PDF using PyMuPDF.

    Returns a dict mapping page number (0-based) to extracted text.
    """
    doc = fitz.open(path)
    texts: Dict[int, str] = {}
    for i, page in enumerate(doc):
        text = page.get_text()
        texts[i] = text
    doc.close()
    return texts


def is_scanned_pdf(texts: Dict[int, str], threshold: float = 0.1) -> bool:
    """Decide if a PDF is scanned based on fraction of pages with little text.

    threshold: fraction of pages with text below which the document is considered scanned.
    """
    if not texts:
        return True
    low_text_pages = sum(1 for t in texts.values() if len((t or "").strip()) < 50)
    frac = low_text_pages / max(1, len(texts))
    return frac >= threshold


def ocr_image_bytes(image_bytes: bytes, lang: str = "eng") -> str:
    """Run OCR on raw image bytes and return extracted text."""
    with Image.open(BytesIO(image_bytes)) as img:
        text = pytesseract.image_to_string(img, lang=lang)
    return text


# Helper to perform OCR on each page image if PDF is scanned
from io import BytesIO


def ocr_pdf(path: str, lang: str = "eng") -> Dict[int, str]:
    """Perform OCR on scanned PDF pages and return per-page text.

    Converts each page to an image and runs pytesseract.
    """
    texts: Dict[int, str] = {}
    doc = fitz.open(path)
    for i, page in enumerate(doc):
        pix = page.get_pixmap(dpi=300)
        img_bytes = pix.tobytes()
        with Image.open(BytesIO(img_bytes)) as img:
            texts[i] = pytesseract.image_to_string(img, lang=lang)
    doc.close()
    return texts

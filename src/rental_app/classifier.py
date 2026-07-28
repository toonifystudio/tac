from __future__ import annotations
from typing import Dict, Any, Optional
import re
import logging

logger = logging.getLogger(__name__)


class ClassificationResult:
    def __init__(self, document_type: str, confidence: float):
        self.document_type = document_type
        self.confidence = confidence


def classify_document(filename: str, ocr_text: Optional[str]) -> ClassificationResult:
    """Simple rule-based classifier using filename and OCR text keywords.

    Returns a ClassificationResult with a document_type key and confidence score.
    """
    fname = filename.lower()
    text = (ocr_text or "").lower()
    # filename heuristics
    if any(x in fname for x in ["application", "rental application", "app"]):
        return ClassificationResult("application", 0.95)
    if any(x in fname for x in ["id", "driver", "license", "passport"]):
        return ClassificationResult("id", 0.9)
    if any(x in fname for x in ["paystub", "pay stubs", "paystub"]):
        return ClassificationResult("paystubs", 0.9)
    if any(x in fname for x in ["bank", "statement"]):
        return ClassificationResult("bank_statements", 0.9)
    if any(x in fname for x in ["1040", "tax", "irs"]):
        return ClassificationResult("tax_return", 0.9)
    # text heuristics
    if "payroll" in text or "employer" in text or re.search(r"\$\d{1,3}[,\d]*", text):
        return ClassificationResult("paystubs", 0.6)
    if "account" in text and "statement" in text:
        return ClassificationResult("bank_statements", 0.6)
    # fallback
    return ClassificationResult("unknown", 0.2)

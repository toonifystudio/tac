from __future__ import annotations
from dataclasses import dataclass
import re

@dataclass
class ClassificationResult:
    document_type: str
    confidence: float = 0.9


def classify_document(filename: str, text: str) -> ClassificationResult:
    fname = (filename or '').lower()
    txt = (text or '').lower()
    # Heuristic rules
    if 'application' in fname or 'rental application' in txt or 'application form' in txt:
        return ClassificationResult('application', 0.95)
    if any(k in fname for k in ('passport', 'driver', 'license')) or any(k in txt for k in ('driver', 'passport', 'id number')):
        return ClassificationResult('id', 0.95)
    if 'pay' in fname or 'pay' in txt or 'paystub' in fname:
        return ClassificationResult('paystubs', 0.9)
    if 'tax' in fname or 'irs' in txt or '1040' in txt:
        return ClassificationResult('tax_return', 0.9)
    if 'bank' in fname or 'statement' in fname or 'account' in txt:
        return ClassificationResult('bank_statements', 0.9)
    if 'employment' in fname or 'employer' in txt or 'employment letter' in txt:
        return ClassificationResult('employment_letter', 0.85)
    if 'support' in fname or 'reference' in txt or 'letter' in txt:
        return ClassificationResult('supporting_documents', 0.7)
    return ClassificationResult('unknown', 0.5)

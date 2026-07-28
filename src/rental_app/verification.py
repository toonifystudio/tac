from __future__ import annotations
from typing import List, Dict, Any, Optional
import logging

from rental_app.config import load_config
from rental_app.models import Application, Document

logger = logging.getLogger(__name__)


class VerificationResult:
    def __init__(self, ok: bool, missing: List[str], issues: List[str]):
        self.ok = ok
        self.missing = missing
        self.issues = issues


def verify_required_documents(application: Application, sess) -> VerificationResult:
    """Verify that an application has required document types according to config.

    This function expects that Document.document_type will be populated by a classifier
    elsewhere. For now classification may be best-effort and missing types will be
    returned in the result.
    """
    cfg = load_config()
    required = cfg.processing.get("required_document_types", [])
    # gather existing types for the application
    docs = sess.query(Document).filter(Document.application_id == application.id).all()
    present = set(d.document_type for d in docs if getattr(d, 'document_type', None))
    missing = [r for r in required if r not in present]
    issues: List[str] = []
    ok = len(missing) == 0
    return VerificationResult(ok=ok, missing=missing, issues=issues)

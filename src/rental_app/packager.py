from __future__ import annotations
from typing import List, Optional
import os
from pathlib import Path
import logging

from rental_app.pdf_utils import merge_pdfs

logger = logging.getLogger(__name__)


def create_package(application_id: int, document_paths: List[str], output_dir: str) -> str:
    """Create a merged PDF package for the application and return output path.

    document_paths: ordered list of file paths to include in the package.
    """
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    out_path = os.path.join(output_dir, f"package_{application_id}.pdf")
    merge_pdfs(document_paths, out_path)
    logger.info("Created package %s for application %s", out_path, application_id)
    return out_path

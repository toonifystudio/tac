import logging
from typing import List
from pathlib import Path
from pypdf import PdfReader, PdfWriter

logger = logging.getLogger(__name__)


def get_pdf_page_count(path: str) -> int:
    reader = PdfReader(path)
    return len(reader.pages)


def merge_pdfs(input_paths: List[str], output_path: str) -> None:
    """Merge PDFs preserving order and write to output_path."""
    writer = PdfWriter()
    for p in input_paths:
        reader = PdfReader(p)
        for page in reader.pages:
            writer.add_page(page)
    with open(output_path, "wb") as fh:
        writer.write(fh)
    logger.info("Merged %d PDFs into %s", len(input_paths), output_path)

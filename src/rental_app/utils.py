from __future__ import annotations
import hashlib
import os
from pathlib import Path
from typing import Optional


def compute_checksum(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def save_attachment_atomic(dir_path: Path, filename: str, data: bytes, checksum_prefix: Optional[str] = None) -> Path:
    """Atomically save an attachment to dir_path with deterministic name based on checksum and filename.

    If a file with the same checksum already exists in dir_path, return that path without writing.
    """
    dir_path.mkdir(parents=True, exist_ok=True)
    checksum = compute_checksum(data)
    safe_name = f"{checksum[:16]}_{filename}"
    dest = dir_path / safe_name
    if dest.exists():
        return dest
    tmp = dir_path / (safe_name + '.tmp')
    with open(tmp, 'wb') as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, dest)
    return dest

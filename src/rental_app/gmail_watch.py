from __future__ import annotations
from typing import Optional, Dict, Any
import logging
from datetime import datetime, timedelta

from rental_app.checkpoints import get_checkpoint, set_checkpoint
from rental_app.db import DB

logger = logging.getLogger(__name__)


def persist_watch_metadata(db: DB, resource_id: str, expiration_ts: int) -> None:
    # store as iso timestamp and resource id
    value = {"resource_id": resource_id, "expiration_ts": expiration_ts}
    set_checkpoint(db, "watch_response", str(value))


def get_watch_metadata(db: DB) -> Optional[Dict[str, Any]]:
    v = get_checkpoint(db, "watch_response")
    if not v:
        return None
    try:
        # value was stored as str(dict) earlier; try eval safely
        return eval(v) if isinstance(v, str) else None
    except Exception:
        return None


def watch_needs_renewal(db: DB, safety_margin_seconds: int = 24 * 3600) -> bool:
    meta = get_watch_metadata(db)
    if not meta:
        return True
    exp = meta.get("expiration_ts")
    if not exp:
        return True
    expiration = datetime.fromtimestamp(int(exp))
    return expiration <= datetime.utcnow() + timedelta(seconds=safety_margin_seconds)

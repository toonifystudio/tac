from __future__ import annotations
from typing import Optional
from sqlalchemy import select
from rental_app.db import DB


def get_checkpoint(db: DB, key: str) -> Optional[str]:
    with db.SessionLocal() as sess:
        res = sess.execute(select("value").select_from("checkpoints").where("key = :k"), {"k": key}).fetchone()
        if res:
            return res[0]
        return None


def set_checkpoint(db: DB, key: str, value: str) -> None:
    # use INSERT OR REPLACE for sqlite; for portability use upsert via simple approach
    with db.SessionLocal() as sess:
        # attempt update
        updated = sess.execute("UPDATE checkpoints SET value = :v WHERE key = :k", {"v": value, "k": key}).rowcount
        if not updated:
            sess.execute("INSERT INTO checkpoints(key, value) VALUES (:k, :v)", {"k": key, "v": value})
        sess.commit()

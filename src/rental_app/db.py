from __future__ import annotations
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from typing import Iterator, Optional

_DEFAULT_ECHO = False


class DB:
    """Database wrapper around SQLAlchemy engine and session factory.

    The DB class encapsulates engine creation so the underlying database URL can be
    swapped (sqlite/postgres) without changing business logic.
    """

    def __init__(self, db_url: Optional[str] = None, echo: bool = _DEFAULT_ECHO):
        db_url = db_url or "sqlite:///./data/tac.db"
        if db_url.startswith("sqlite:///"):
            path = db_url.replace("sqlite:///", "")
            dir_path = os.path.dirname(path)
            if dir_path and not os.path.exists(dir_path):
                os.makedirs(dir_path, exist_ok=True)
        self.engine = create_engine(db_url, echo=echo, future=True)
        self.SessionLocal = sessionmaker(bind=self.engine, expire_on_commit=False, class_=Session)

    def create_all(self, base) -> None:
        """Create all tables for the provided declarative base."""
        base.metadata.create_all(self.engine)

    def drop_all(self, base) -> None:
        """Drop all tables for the provided declarative base."""
        base.metadata.drop_all(self.engine)

    def session(self) -> Iterator[Session]:
        sess = self.SessionLocal()
        try:
            yield sess
        finally:
            sess.close()

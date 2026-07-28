from __future__ import annotations
from typing import List, Dict, Any, Optional
import importlib
import pkgutil
import logging
from sqlalchemy import create_engine, Table, Column, Integer, String, MetaData, select

logger = logging.getLogger(__name__)

MIGRATIONS_TABLE = 'schema_migrations'


def _ensure_migrations_table(engine):
    meta = MetaData()
    if MIGRATIONS_TABLE in meta.tables:
        return
    tbl = Table(
        MIGRATIONS_TABLE,
        meta,
        Column('id', Integer, primary_key=True),
        Column('version', String(64), unique=True, nullable=False),
    )
    meta.create_all(engine, tables=[tbl])


def _applied_migrations(engine) -> List[str]:
    meta = MetaData(bind=engine)
    meta.reflect()
    if MIGRATIONS_TABLE not in meta.tables:
        return []
    tbl = meta.tables[MIGRATIONS_TABLE]
    with engine.connect() as conn:
        rows = conn.execute(select(tbl.c.version)).fetchall()
    return [r[0] for r in rows]


def apply_migrations(db_url: str) -> None:
    engine = create_engine(db_url, future=True)
    _ensure_migrations_table(engine)
    applied = set(_applied_migrations(engine))
    package = 'rental_app.migrations.versions'
    try:
        importlib.import_module(package)
    except Exception:
        logger.debug('No migrations package found')
        return
    for finder, name, ispkg in pkgutil.iter_modules(importlib.import_module(package).__path__):
        module_name = f"{package}.{name}"
        mod = importlib.import_module(module_name)
        version = getattr(mod, 'version', None)
        if not version or version in applied:
            continue
        logger.info('Applying migration %s', version)
        upgrade = getattr(mod, 'upgrade', None)
        if not callable(upgrade):
            logger.warning('Migration %s has no upgrade callable', version)
            continue
        with engine.begin() as conn:
            upgrade(conn)
            meta = MetaData()
            meta.reflect(bind=conn)
            tbl = Table(MIGRATIONS_TABLE, meta, autoload_with=conn)
            conn.execute(tbl.insert().values(version=version))
        logger.info('Applied migration %s', version)

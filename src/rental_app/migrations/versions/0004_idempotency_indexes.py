# Migration: add unique constraints/indexes for idempotency
version = '0004_idempotency_indexes'

from sqlalchemy import text


def upgrade(conn):
    # Create unique indexes to prevent duplicate documents, packages, drafts
    # SQLite: use CREATE UNIQUE INDEX IF NOT EXISTS
    conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ux_documents_app_checksum ON documents (application_id, checksum)"))
    conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ux_packages_app_checksum ON packages (application_id, checksum)"))
    conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ux_drafts_app_draftid ON drafts (application_id, draft_id)"))

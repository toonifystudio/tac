# Migration: alter documents table to add OCR/classification fields and add packages/drafts/checkpoints
version = '0003_documents_packages_drafts'

from sqlalchemy import Table, Column, Integer, String, MetaData, Text, ForeignKey


def upgrade(conn):
    meta = MetaData()
    meta.reflect(bind=conn)
    # Add columns to documents if missing (SQLite supports ADD COLUMN)
    if 'documents' in meta.tables:
        try:
            conn.execute('ALTER TABLE documents ADD COLUMN document_type VARCHAR(128)')
        except Exception:
            pass
        try:
            conn.execute('ALTER TABLE documents ADD COLUMN ocr_text TEXT')
        except Exception:
            pass
        try:
            conn.execute('ALTER TABLE documents ADD COLUMN pages INTEGER')
        except Exception:
            pass
    else:
        documents = Table(
            'documents',
            meta,
            Column('id', Integer, primary_key=True),
            Column('application_id', Integer, ForeignKey('applications.id')),
            Column('filename', String(512)),
            Column('path', String(1024)),
            Column('checksum', String(128)),
            Column('size_bytes', Integer),
            Column('created_at', String),
            Column('document_type', String(128)),
            Column('ocr_text', Text),
            Column('pages', Integer),
        )
        meta.create_all(conn)

    # create packages table
    if 'packages' not in meta.tables:
        packages = Table(
            'packages',
            meta,
            Column('id', Integer, primary_key=True),
            Column('application_id', Integer, ForeignKey('applications.id')),
            Column('package_path', String(1024)),
            Column('checksum', String(128)),
            Column('metadata', String),
            Column('created_at', String),
        )
        meta.create_all(conn, tables=[packages])

    # create drafts table
    if 'drafts' not in meta.tables:
        drafts = Table(
            'drafts',
            meta,
            Column('id', Integer, primary_key=True),
            Column('application_id', Integer, ForeignKey('applications.id')),
            Column('draft_id', String(256)),
            Column('to', String(512)),
            Column('subject', String(512)),
            Column('body', Text),
            Column('created_at', String),
        )
        meta.create_all(conn, tables=[drafts])

    # create checkpoints table if missing
    if 'checkpoints' not in meta.tables:
        checkpoints = Table(
            'checkpoints',
            meta,
            Column('id', Integer, primary_key=True),
            Column('key', String(128), nullable=False, unique=True),
            Column('value', Text),
        )
        meta.create_all(conn, tables=[checkpoints])

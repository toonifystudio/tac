# Migration: add reviewer_notes table
version = '0005_review_notes'

from sqlalchemy import Table, Column, Integer, String, MetaData, Text, ForeignKey


def upgrade(conn):
    meta = MetaData()
    meta.reflect(bind=conn)
    if 'reviewer_notes' not in meta.tables:
        notes = Table(
            'reviewer_notes',
            meta,
            Column('id', Integer, primary_key=True),
            Column('application_id', Integer, ForeignKey('applications.id')),
            Column('reviewer', String(128)),
            Column('note', Text),
            Column('created_at', String),
        )
        meta.create_all(conn, tables=[notes])

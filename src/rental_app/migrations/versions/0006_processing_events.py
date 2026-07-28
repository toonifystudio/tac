# Migration: add processing_events table
version = '0006_processing_events'

from sqlalchemy import Table, Column, Integer, String, MetaData, Text, ForeignKey


def upgrade(conn):
    meta = MetaData()
    meta.reflect(bind=conn)
    if 'processing_events' not in meta.tables:
        ev = Table(
            'processing_events',
            meta,
            Column('id', Integer, primary_key=True),
            Column('application_id', Integer, ForeignKey('applications.id')),
            Column('event_type', String(128)),
            Column('message', Text),
            Column('created_at', String),
        )
        meta.create_all(conn, tables=[ev])

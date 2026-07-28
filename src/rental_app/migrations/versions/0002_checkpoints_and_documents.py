# Migration: add checkpoints and documents tables
version = '0002_checkpoints_and_documents'

from sqlalchemy import Table, Column, Integer, String, MetaData, JSON, DateTime, Text, ForeignKey


def upgrade(conn):
    meta = MetaData()
    checkpoints = Table(
        'checkpoints',
        meta,
        Column('id', Integer, primary_key=True),
        Column('key', String(128), nullable=False, unique=True),
        Column('value', Text),
    )
    documents = Table(
        'documents',
        meta,
        Column('id', Integer, primary_key=True),
        Column('application_id', Integer, ForeignKey('applications.id')),
        Column('filename', String(512)),
        Column('path', String(1024)),
        Column('checksum', String(128)),
        Column('size_bytes', Integer),
        Column('created_at', DateTime),
    )
    meta.create_all(conn)

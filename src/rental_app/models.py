from __future__ import annotations
from datetime import datetime
from typing import Any, Dict
from sqlalchemy import (
    Column,
    Integer,
    String,
    DateTime,
    Text,
    ForeignKey,
    JSON,
    UniqueConstraint,
    Index,
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class EmailRecord(Base):
    __tablename__ = "email_records"
    id = Column(Integer, primary_key=True)
    message_id = Column(String(256), unique=True, nullable=False)
    sender = Column(String(256), nullable=False)
    sender_email = Column(String(256), nullable=True)
    subject = Column(String(512), nullable=True)
    received_at = Column(DateTime, default=datetime.utcnow)
    raw_headers = Column(JSON, default={})
    raw_payload = Column(JSON, default={})
    application = relationship("Application", back_populates="email_record", uselist=False)


class Application(Base):
    __tablename__ = "applications"
    __table_args__ = (
        UniqueConstraint("message_id", name="uq_app_message_id"),
        Index("ix_app_processing_id", "processing_id"),
        Index("ix_app_state", "state"),
    )
    id = Column(Integer, primary_key=True)
    message_id = Column(String(256), nullable=False, unique=True)
    processing_id = Column(String(64), nullable=False, index=True)
    state = Column(String(64), nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    history_id = Column(String(64), nullable=True)
    last_error = Column(Text, nullable=True)
    retry_count = Column(Integer, default=0)
    meta = Column(JSON, default={})
    email_record_id = Column(Integer, ForeignKey("email_records.id"), nullable=True)
    email_record = relationship("EmailRecord", back_populates="application")


class Document(Base):
    __tablename__ = "documents"
    id = Column(Integer, primary_key=True)
    application_id = Column(Integer, ForeignKey("applications.id"), nullable=False)
    filename = Column(String(512))
    path = Column(String(1024))
    checksum = Column(String(128))
    size_bytes = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)

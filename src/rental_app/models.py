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
    documents = relationship("Document", back_populates="application", cascade="all, delete-orphan")
    packages = relationship("Package", back_populates="application", cascade="all, delete-orphan")


class Document(Base):
    __tablename__ = "documents"
    id = Column(Integer, primary_key=True)
    application_id = Column(Integer, ForeignKey("applications.id"), nullable=False)
    filename = Column(String(512))
    path = Column(String(1024))
    checksum = Column(String(128))
    size_bytes = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)
    # New fields
    document_type = Column(String(128), nullable=True)
    ocr_text = Column(Text, nullable=True)
    pages = Column(Integer, nullable=True)

    application = relationship("Application", back_populates="documents")


class Package(Base):
    __tablename__ = "packages"
    id = Column(Integer, primary_key=True)
    application_id = Column(Integer, ForeignKey("applications.id"), nullable=False)
    package_path = Column(String(1024))
    checksum = Column(String(128))
    metadata = Column(JSON, default={})
    created_at = Column(DateTime, default=datetime.utcnow)

    application = relationship("Application", back_populates="packages")


class Draft(Base):
    __tablename__ = "drafts"
    id = Column(Integer, primary_key=True)
    application_id = Column(Integer, ForeignKey("applications.id"), nullable=False)
    draft_id = Column(String(256))
    to = Column(String(512))
    subject = Column(String(512))
    body = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

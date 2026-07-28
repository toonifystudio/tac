from __future__ import annotations
from typing import List
from unittest.mock import MagicMock
import pytest
from rental_app.gmail_pipeline import GmailClient
from rental_app.credential_store import KeyringCredentialStore
from rental_app.db import DB
from rental_app.models import Base, Document


def test_duplicate_processing_should_not_duplicate_documents(tmp_path, monkeypatch):
    db_path = tmp_path / "tac.db"
    db = DB(db_url=f"sqlite:///{db_path}")
    Base.metadata.create_all(db.engine)

    # fake service
    fake_service = MagicMock()
    message_id = 'm-dup'
    fake_msg = {
        'payload': {
            'headers': [{'name': 'From', 'value': 'Tomeka <tomeka@example.com>'}],
            'parts': [
                {'filename': 'app.pdf', 'mimeType': 'application/pdf', 'body': {'attachmentId': 'a-1'}}
            ]
        },
        'historyId': 'h-dup'
    }
    fake_service.users.return_value.messages.return_value.get.return_value.execute.return_value = fake_msg
    data_b64 = 'aGVsbG8='
    fake_service.users.return_value.messages.return_value.attachments.return_value.get.return_value.execute.return_value = {'data': data_b64}

    client = GmailClient(credential_store=MagicMock(spec=KeyringCredentialStore), db=db)
    client.set_service(fake_service)
    client.cfg.approved_agents['emails'] = ['tomeka@example.com']

    app1 = client.process_message(message_id)
    app2 = client.process_message(message_id)
    assert app1.id == app2.id
    with db.SessionLocal() as sess:
        docs = sess.query(Document).filter(Document.application_id == app1.id).all()
        assert len(docs) == 1

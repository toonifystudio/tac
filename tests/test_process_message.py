from unittest.mock import MagicMock, patch
import tempfile
import os
from rental_app.gmail_client import GmailClient
from rental_app.credential_store import KeyringCredentialStore
from rental_app.db import DB
from rental_app.models import Base, Application, Document


def test_process_message_download(tmp_path, monkeypatch):
    # Setup DB
    db_path = tmp_path / "tac.db"
    db = DB(db_url=f"sqlite:///{db_path}")
    Base.metadata.create_all(db.engine)

    # Create fake service
    fake_service = MagicMock()
    # Simulate message.get returning a payload with one attachment part
    message_id = 'm-1'
    fake_msg = {
        'payload': {
            'headers': [{'name': 'From', 'value': 'Tomeka <tomeka@example.com>'}, {'name': 'Subject', 'value': 'App'}],
            'parts': [
                {'filename': 'app.pdf', 'mimeType': 'application/pdf', 'body': {'attachmentId': 'a-1'}}
            ]
        },
        'historyId': 'h-1'
    }
    fake_service.users.return_value.messages.return_value.get.return_value.execute.return_value = fake_msg
    # attachments.get returns data
    data_b64 = 'aGVsbG8='  # 'hello'
    fake_service.users.return_value.messages.return_value.attachments.return_value.get.return_value.execute.return_value = {'data': data_b64}

    client = GmailClient(credential_store=MagicMock(spec=KeyringCredentialStore), db=db)
    client.set_service(fake_service)
    # Ensure config approved emails includes tomeka@example.com
    client.cfg.approved_agents['emails'] = ['tomeka@example.com']

    app = client.process_message(message_id)
    assert app is not None
    # verify document recorded
    with db.SessionLocal() as sess:
        docs = sess.query(Document).filter(Document.application_id == app.id).all()
        assert len(docs) == 1

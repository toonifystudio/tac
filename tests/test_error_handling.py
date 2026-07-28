from unittest.mock import MagicMock, patch
from rental_app.gmail_pipeline import GmailClient
from rental_app.credential_store import KeyringCredentialStore
from rental_app.db import DB
from rental_app.models import Base
import pytest


def test_failed_ocr_moves_to_error(tmp_path, monkeypatch):
    db_path = tmp_path / "tac.db"
    db = DB(db_url=f"sqlite:///{db_path}")
    Base.metadata.create_all(db.engine)

    fake_service = MagicMock()
    message_id = 'm-err'
    fake_msg = {
        'payload': {
            'headers': [{'name': 'From', 'value': 'Tomeka <tomeka@example.com>'}],
            'parts': [
                {'filename': 'bad.pdf', 'mimeType': 'application/pdf', 'body': {'attachmentId': 'a-1'}}
            ]
        },
        'historyId': 'h-err'
    }
    fake_service.users.return_value.messages.return_value.get.return_value.execute.return_value = fake_msg
    data_b64 = 'aGVsbG8='
    fake_service.users.return_value.messages.return_value.attachments.return_value.get.return_value.execute.return_value = {'data': data_b64}

    client = GmailClient(credential_store=MagicMock(spec=KeyringCredentialStore), db=db)
    client.set_service(fake_service)
    client.cfg.approved_agents['emails'] = ['tomeka@example.com']

    # force OCR to raise
    monkeypatch.setattr('rental_app.ocr.extract_text_from_pdf', lambda p: (_ for _ in ()).throw(Exception('OCR failure')))
    app = client.process_message(message_id)
    assert app is not None
    with db.SessionLocal() as sess:
        a = sess.query(Base.classes.applications).first() if hasattr(Base, 'classes') else None
        # fall back: check application last_error exists or state==ERROR
        from rental_app.models import Application
        app_rec = sess.query(Application).filter(Application.message_id == message_id).first()
        assert app_rec is not None
        assert app_rec.state == 'Error' or app_rec.last_error is not None

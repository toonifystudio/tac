from unittest.mock import MagicMock, patch
import tempfile
import os
from rental_app.gmail_pipeline import GmailClient
from rental_app.credential_store import KeyringCredentialStore
from rental_app.db import DB
from rental_app.models import Base, Application, Document, Package, Draft


def test_full_processing_flow(tmp_path, monkeypatch):
    # Setup DB
    db_path = tmp_path / "tac.db"
    db = DB(db_url=f"sqlite:///{db_path}")
    Base.metadata.create_all(db.engine)

    # Fake service
    fake_service = MagicMock()
    message_id = 'm-100'
    fake_msg = {
        'payload': {
            'headers': [{'name': 'From', 'value': 'Tomeka <tomeka@example.com>'}, {'name': 'Subject', 'value': 'App'}],
            'parts': [
                {'filename': 'app.pdf', 'mimeType': 'application/pdf', 'body': {'attachmentId': 'a-1'}},
                {'filename': 'id.pdf', 'mimeType': 'application/pdf', 'body': {'attachmentId': 'a-2'}}
            ]
        },
        'historyId': 'h-100'
    }
    fake_service.users.return_value.messages.return_value.get.return_value.execute.return_value = fake_msg
    # attachments.get returns small pdf bytes (we'll write simple PDF bytes)
    sample_pdf = b"%PDF-1.4\n1 0 obj<</Type /Catalog>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n"
    import base64
    data_b64 = base64.urlsafe_b64encode(sample_pdf).decode('utf-8')
    fake_service.users.return_value.messages.return_value.attachments.return_value.get.return_value.execute.return_value = {'data': data_b64}
    # draft creation
    fake_service.users.return_value.drafts.return_value.create.return_value.execute.return_value = {'id': 'draft-1'}

    client = GmailClient(credential_store=MagicMock(spec=KeyringCredentialStore), db=db)
    client.set_service(fake_service)
    client.cfg.approved_agents['emails'] = ['tomeka@example.com']
    # monkeypatch OCR/classifier/packager to avoid heavy deps
    monkeypatch.setattr('rental_app.ocr.extract_text_from_pdf', lambda p: {0: 'name: Alice'})
    monkeypatch.setattr('rental_app.ocr.is_scanned_pdf', lambda texts: False)
    monkeypatch.setattr('rental_app.classifier.classify_document', lambda fn, txt: type('R',(),{'document_type':'application','confidence':0.9})())
    monkeypatch.setattr('rental_app.packager.create_package', lambda aid, paths, out: str(tmp_path / f'package_{aid}.pdf'))

    app = client.process_message(message_id)
    assert app is not None
    with db.SessionLocal() as sess:
        docs = sess.query(Document).filter(Document.application_id == app.id).all()
        assert len(docs) >= 2
        pkgs = sess.query(Package).filter(Package.application_id == app.id).all()
        assert len(pkgs) == 1
        drafts = sess.query(Draft).filter(Draft.application_id == app.id).all()
        assert len(drafts) == 1

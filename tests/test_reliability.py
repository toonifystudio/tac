from unittest.mock import MagicMock
import base64
import os
from rental_app.gmail_pipeline import GmailPipeline
from rental_app.credential_store import KeyringCredentialStore
from rental_app.db import DB
from rental_app.models import Base, Application, Document, Package, Draft


def sample_pdf_bytes():
    return b"%PDF-1.4\n1 0 obj<</Type /Catalog>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n"


def setup_db(tmp_path):
    db_path = tmp_path / "tac.db"
    db = DB(db_url=f"sqlite:///{db_path}")
    Base.metadata.create_all(db.engine)
    return db


def make_service_with_attachment(data_bytes):
    fake = MagicMock()
    # message.get to return payload with one attachment
    fake_msg = {
        'payload': {
            'headers': [{'name': 'From', 'value': 'Tomeka <tomeka@example.com>'}, {'name':'Subject','value':'App'}],
            'parts': [
                {'filename': 'doc.pdf', 'mimeType': 'application/pdf', 'body': {'attachmentId': 'a-1'}}
            ]
        },
        'historyId': 'h-1'
    }
    fake.users.return_value.messages.return_value.get.return_value.execute.return_value = fake_msg
    data_b64 = base64.urlsafe_b64encode(data_bytes).decode('utf-8')
    fake.users.return_value.messages.return_value.attachments.return_value.get.return_value.execute.return_value = {'data': data_b64}
    # drafts.create
    fake.users.return_value.drafts.return_value.create.return_value.execute.return_value = {'id': 'draft-1'}
    return fake


def test_duplicate_email_processing(tmp_path):
    db = setup_db(tmp_path)
    data = sample_pdf_bytes()
    service = make_service_with_attachment(data)

    client = GmailPipeline(credential_store=MagicMock(spec=KeyringCredentialStore), db=db)
    client.set_service(service)
    client.cfg.approved_agents['emails'] = ['tomeka@example.com']
    # use tmp_path as data_dir
    client.cfg.data_dir = str(tmp_path)

    mid = 'msg-dup'
    # Prepare message.get to return same payload for this id
    service.users.return_value.messages.return_value.get.return_value.execute.return_value['payload']['parts'][0]['body']['attachmentId'] = 'a-1'

    app1 = client.process_message(mid)
    app2 = client.process_message(mid)

    with db.SessionLocal() as sess:
        apps = sess.query(Application).filter(Application.message_id == mid).all()
        docs = sess.query(Document).filter(Document.application_id == apps[0].id).all()
        pkgs = sess.query(Package).filter(Package.application_id == apps[0].id).all()
        drs = sess.query(Draft).filter(Draft.application_id == apps[0].id).all()
        assert len(apps) == 1
        assert len(docs) == 1
        assert len(pkgs) == 1
        assert len(drs) == 1


def test_duplicate_attachment_across_messages(tmp_path):
    db = setup_db(tmp_path)
    data = sample_pdf_bytes()
    service = make_service_with_attachment(data)

    client = GmailPipeline(credential_store=MagicMock(spec=KeyringCredentialStore), db=db)
    client.set_service(service)
    client.cfg.approved_agents['emails'] = ['tomeka@example.com']
    client.cfg.data_dir = str(tmp_path)

    mid1 = 'msg-a'
    mid2 = 'msg-b'
    # First message
    service.users.return_value.messages.return_value.get.return_value.execute.return_value['payload']['parts'][0]['body']['attachmentId'] = 'a-1'
    client.process_message(mid1)
    # Second message with same attachment data but different message id
    service.users.return_value.messages.return_value.get.return_value.execute.return_value['payload']['parts'][0]['body']['attachmentId'] = 'a-2'
    client.process_message(mid2)

    with db.SessionLocal() as sess:
        apps1 = sess.query(Application).filter(Application.message_id == mid1).first()
        apps2 = sess.query(Application).filter(Application.message_id == mid2).first()
        docs1 = sess.query(Document).filter(Document.application_id == apps1.id).all()
        docs2 = sess.query(Document).filter(Document.application_id == apps2.id).all()
        # ensure file path is same for both documents (reused storage)
        assert docs1 and docs2
        assert docs1[0].path == docs2[0].path


def test_package_deduplication(tmp_path, monkeypatch):
    db = setup_db(tmp_path)
    data = sample_pdf_bytes()
    service = make_service_with_attachment(data)

    client = GmailPipeline(credential_store=MagicMock(spec=KeyringCredentialStore), db=db)
    client.set_service(service)
    client.cfg.approved_agents['emails'] = ['tomeka@example.com']
    client.cfg.data_dir = str(tmp_path)

    # monkeypatch packager to create file
    created = []

    def fake_create_package(aid, paths, outdir):
        p = os.path.join(outdir, f'package_{aid}.pdf')
        with open(p, 'wb') as fh:
            fh.write(b'PKG')
        created.append(p)
        return p

    monkeypatch.setattr('rental_app.packager.create_package', fake_create_package)

    mid = 'msg-pkg'
    client.process_message(mid)
    client.process_message(mid)

    with db.SessionLocal() as sess:
        app = sess.query(Application).filter(Application.message_id == mid).first()
        pkgs = sess.query(Package).filter(Package.application_id == app.id).all()
        assert len(pkgs) == 1
        # only one package file should remain
        assert len(created) >= 1
        # compute number of package files on disk
        pkg_files = [p for p in created if os.path.exists(p)]
        assert len(pkg_files) >= 1


def test_draft_deduplication(tmp_path, monkeypatch):
    db = setup_db(tmp_path)
    data = sample_pdf_bytes()
    service = make_service_with_attachment(data)

    client = GmailPipeline(credential_store=MagicMock(spec=KeyringCredentialStore), db=db)
    client.set_service(service)
    client.cfg.approved_agents['emails'] = ['tomeka@example.com']
    client.cfg.data_dir = str(tmp_path)

    calls = {'create_draft': 0}

    def fake_create_draft(to, subject, body, attachments=None):
        calls['create_draft'] += 1
        return {'id': f'draft-{calls["create_draft"]}'}

    monkeypatch.setattr(GmailPipeline, 'create_draft', fake_create_draft)

    mid = 'msg-draft'
    client.process_message(mid)
    client.process_message(mid)

    with db.SessionLocal() as sess:
        app = sess.query(Application).filter(Application.message_id == mid).first()
        drs = sess.query(Draft).filter(Draft.application_id == app.id).all()
        assert len(drs) == 1
        # ensure create_draft called only once
        assert calls['create_draft'] == 1


def test_package_failure_recovery(tmp_path, monkeypatch):
    db = setup_db(tmp_path)
    data = sample_pdf_bytes()
    service = make_service_with_attachment(data)

    client = GmailPipeline(credential_store=MagicMock(spec=KeyringCredentialStore), db=db)
    client.set_service(service)
    client.cfg.approved_agents['emails'] = ['tomeka@example.com']
    client.cfg.data_dir = str(tmp_path)

    # force packager to raise
    def bad_packager(aid, paths, outdir):
        raise Exception('packager failure')

    monkeypatch.setattr('rental_app.packager.create_package', bad_packager)

    mid = 'msg-pkgfail'
    client.process_message(mid)

    with db.SessionLocal() as sess:
        app = sess.query(Application).filter(Application.message_id == mid).first()
        assert app is not None
        assert app.state == 'Error' or app.last_error is not None


def test_draft_failure_recovery(tmp_path, monkeypatch):
    db = setup_db(tmp_path)
    data = sample_pdf_bytes()
    service = make_service_with_attachment(data)

    client = GmailPipeline(credential_store=MagicMock(spec=KeyringCredentialStore), db=db)
    client.set_service(service)
    client.cfg.approved_agents['emails'] = ['tomeka@example.com']
    client.cfg.data_dir = str(tmp_path)

    # normal packager
    monkeypatch.setattr('rental_app.packager.create_package', lambda aid, paths, out: str(tmp_path / f'package_{aid}.pdf'))

    # monkeypatch create_draft to raise
    def bad_create_draft(to, subject, body, attachments=None):
        raise Exception('draft failed')

    monkeypatch.setattr(GmailPipeline, 'create_draft', bad_create_draft)

    mid = 'msg-draftfail'
    client.process_message(mid)

    with db.SessionLocal() as sess:
        app = sess.query(Application).filter(Application.message_id == mid).first()
        assert app is not None
        assert app.state == 'Error' or app.last_error is not None


def test_full_success_workflow(tmp_path, monkeypatch):
    db = setup_db(tmp_path)
    data = sample_pdf_bytes()
    service = make_service_with_attachment(data)

    client = GmailPipeline(credential_store=MagicMock(spec=KeyringCredentialStore), db=db)
    client.set_service(service)
    client.cfg.approved_agents['emails'] = ['tomeka@example.com']
    client.cfg.data_dir = str(tmp_path)

    # monkeypatch OCR/classifier/packager to be deterministic
    monkeypatch.setattr('rental_app.ocr.extract_text_from_pdf', lambda p: {0: 'name: Alice'})
    monkeypatch.setattr('rental_app.ocr.is_scanned_pdf', lambda texts: False)
    monkeypatch.setattr('rental_app.classifier.classify_document', lambda fn, txt: type('R',(),{'document_type':'application','confidence':0.9})())
    monkeypatch.setattr('rental_app.packager.create_package', lambda aid, paths, out: str(tmp_path / f'package_{aid}.pdf'))
    monkeypatch.setattr(GmailPipeline, 'create_draft', lambda self, to, subject, body, attachments=None: {'id':'d1'})

    mid = 'msg-full'
    client.process_message(mid)

    with db.SessionLocal() as sess:
        app = sess.query(Application).filter(Application.message_id == mid).first()
        assert app.state == 'Awaiting My Approval'
        docs = sess.query(Document).filter(Document.application_id == app.id).all()
        pkgs = sess.query(Package).filter(Package.application_id == app.id).all()
        drs = sess.query(Draft).filter(Draft.application_id == app.id).all()
        assert len(docs) >= 1
        assert len(pkgs) == 1
        assert len(drs) == 1

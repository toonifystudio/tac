from __future__ import annotations
from typing import Optional, List
import logging
import base64
import os
from pathlib import Path
import hashlib

from sqlalchemy.exc import IntegrityError

from rental_app.config import load_config
from rental_app.credential_store import CredentialStore
from rental_app.db import DB
from rental_app.models import EmailRecord, Document, Application, Package, Draft
from rental_app.state_machine import ApplicationStateMachine, State
from rental_app.logging_config import get_logger
from rental_app.utils import save_attachment_atomic, compute_checksum
from rental_app.gmail_enhancements import GmailClientEnhancements
from rental_app import ocr, classifier, verification, packager

logger = logging.getLogger(__name__)


class GmailPipeline:
    """Idempotent, transactional Gmail processing pipeline.

    High-level steps (each made idempotent and transactional):
      - Fetch message
      - Record EmailRecord
      - Create or get Application
      - Download attachments (atomic, dedupe by checksum)
      - OCR/classify documents (idempotent)
      - Verify required documents
      - Create package (idempotent)
      - Create draft (idempotent)
    """

    def __init__(self, credential_store: CredentialStore, db: Optional[DB] = None, config_path: Optional[str] = None):
        self.credential_store = credential_store
        self.cfg = load_config(config_path)
        self.db = db or DB(db_url=f"sqlite:///{self.cfg.db_path}")
        self._service = None
        self.enh = GmailClientEnhancements(credential_store, db=self.db, config_path=config_path)

    def set_service(self, service_obj):
        self._service = service_obj
        self.enh.set_service(service_obj)

    def _get_header_value(self, headers, name: str) -> Optional[str]:
        for h in headers:
            if h.get("name", "").lower() == name.lower():
                return h.get("value")
        return None

    def _parse_sender(self, from_header: Optional[str]) -> (Optional[str], Optional[str]):
        if not from_header:
            return None, None
        if "<" in from_header and ">" in from_header:
            try:
                name_part, email_part = from_header.rsplit("<", 1)
                email = email_part.strip(" >")
                name = name_part.strip().strip('"')
                return name, email
            except Exception:
                pass
        if "@" in from_header:
            return None, from_header.strip()
        return from_header.strip(), None

    def process_message(self, message_id: str) -> Optional[Application]:
        if not self._service:
            raise RuntimeError("Gmail service not set")

        # fetch message
        try:
            msg = self._service.users().messages().get(userId='me', id=message_id, format='full').execute()
        except Exception as exc:
            logger.exception('Failed to fetch message %s: %s', message_id, exc)
            return None

        payload = msg.get('payload', {})
        headers = payload.get('headers', [])
        from_hdr = self._get_header_value(headers, 'From')
        subject = self._get_header_value(headers, 'Subject') or ''
        history_id = msg.get('historyId')
        name, sender_email = self._parse_sender(from_hdr)
        sender_email = (sender_email or name or '').lower()

        # Build initial context logger without application_id yet
        processing_id = None
        ctx_log = get_logger('tac.pipeline', processing_id=processing_id, message_id=message_id)

        approved_emails = [e.lower() for e in self.cfg.approved_agents.get('emails', [])]

        # First transaction: record EmailRecord and create/get Application and download attachments
        try:
            with self.db.SessionLocal() as sess:
                with sess.begin():
                    # record email if missing
                    existing_email = sess.query(EmailRecord).filter(EmailRecord.message_id == message_id).first()
                    if not existing_email:
                        er = EmailRecord(message_id=message_id, sender=name or '', sender_email=sender_email, subject=subject, raw_headers=headers, raw_payload=payload)
                        sess.add(er)
                        sess.flush()
                    # check approved
                    if sender_email not in approved_emails:
                        ctx_log = get_logger('tac.pipeline', processing_id=None, message_id=message_id, application_id=None)
                        ctx_log.info('Message not from approved sender; skipping', extra={})
                        return None
                    # create or get application
                    machine = ApplicationStateMachine(sess)
                    app = machine.create_application_if_missing(message_id, history_id=history_id)
                    processing_id = app.processing_id
                    # update ctx logger to include application_id and processing_id
                    ctx_log = get_logger('tac.pipeline', processing_id=processing_id, message_id=message_id, application_id=app.id)
                    # if already past NEW, skip downloads
                    sess.refresh(app)
                    if app.state != State.NEW.value:
                        ctx_log.info('Application already processed to state %s; skipping downloads', extra={'state': app.state})
                    else:
                        # traverse parts and download attachments idempotently
                        parts = payload.get('parts') or []

                        def walk(parts_list):
                            for part in parts_list:
                                filename = part.get('filename')
                                body = part.get('body', {})
                                if filename and body.get('attachmentId'):
                                    aid = body.get('attachmentId')
                                    try:
                                        att = self._service.users().messages().attachments().get(userId='me', messageId=message_id, id=aid).execute()
                                        data_b64 = att.get('data')
                                        if not data_b64:
                                            ctx_log.warning('Attachment %s has no data', aid)
                                            continue
                                        raw = base64.urlsafe_b64decode(data_b64.encode('utf-8'))
                                        checksum = compute_checksum(raw)
                                        # Check if a document with this checksum already exists anywhere
                                        existing_doc = sess.query(Document).filter(Document.checksum == checksum).first()
                                        if existing_doc:
                                            # if document already linked to this application, skip
                                            already_linked = sess.query(Document).filter(Document.application_id == app.id, Document.checksum == checksum).first()
                                            if already_linked:
                                                ctx_log.info('Attachment already linked to application, skipping', extra={'checksum': checksum})
                                                continue
                                            # else, create a new Document row referencing same path
                                            doc = Document(application_id=app.id, filename=filename, path=existing_doc.path, checksum=checksum, size_bytes=existing_doc.size_bytes)
                                            sess.add(doc)
                                            sess.flush()
                                            ctx_log.info('Reused existing attachment for new application', extra={'checksum': checksum, 'path': existing_doc.path})
                                            continue
                                        # else save file atomically
                                        attach_dir = Path(self.cfg.data_dir) / 'attachments'
                                        dest = save_attachment_atomic(attach_dir, filename, raw)
                                        # insert Document row; guard against race with unique index
                                        try:
                                            doc = Document(application_id=app.id, filename=filename, path=str(dest), checksum=checksum, size_bytes=len(raw))
                                            sess.add(doc)
                                            sess.flush()
                                            ctx_log.info('Saved attachment', extra={'checksum': checksum, 'path': str(dest)})
                                        except IntegrityError:
                                            sess.rollback()
                                            # another process wrote same document concurrently; try to fetch it
                                            doc = sess.query(Document).filter(Document.application_id == app.id, Document.checksum == checksum).first()
                                            if not doc:
                                                # find by checksum globally
                                                doc = sess.query(Document).filter(Document.checksum == checksum).first()
                                                if doc:
                                                    # link to this application
                                                    newdoc = Document(application_id=app.id, filename=filename, path=doc.path, checksum=checksum, size_bytes=doc.size_bytes)
                                                    sess.add(newdoc)
                                                    sess.flush()
                                    except Exception as exc:
                                        ctx_log.exception('Failed to download attachment %s: %s', aid, exc)
                                if part.get('parts'):
                                    walk(part.get('parts'))

                        walk(parts)
                        # Transition to DOWNLOADED if attachments processed
                        machine.transition(app, State.DOWNLOADED, reason='Downloaded attachments')
                # commit transaction end
        except Exception as exc:
            # top-level failure during download phase
            try:
                with self.db.SessionLocal() as sess:
                    # mark app Error if exists
                    app = sess.query(Application).filter(Application.message_id == message_id).first()
                    if app:
                        app.last_error = f'DOWNLOAD_FAILED: {str(exc)[:200]}'
                        app.state = State.ERROR.value
                        sess.add(app)
                        sess.commit()
            except Exception:
                pass
            logger.exception('Processing failed during download phase for %s: %s', message_id, exc)
            return None

        # OCR / Classification / Verification phase
        try:
            with self.db.SessionLocal() as sess:
                with sess.begin():
                    app = sess.query(Application).filter(Application.message_id == message_id).first()
                    ctx_log = get_logger('tac.pipeline', processing_id=app.processing_id, message_id=message_id, application_id=app.id)
                    docs = sess.query(Document).filter(Document.application_id == app.id).all()
                    for d in docs:
                        # idempotent: skip if ocr_text and document_type already present
                        if d.ocr_text and d.document_type:
                            ctx_log.debug('Skipping OCR/classify for doc (already done)', extra={'doc_id': d.id, 'checksum': d.checksum})
                            continue
                        try:
                            texts = {}
                            try:
                                texts = ocr.extract_text_from_pdf(d.path)
                            except Exception:
                                texts = {}
                            is_scanned = ocr.is_scanned_pdf(texts)
                            if is_scanned:
                                ocr_texts = ocr.ocr_pdf(d.path)
                                combined = '\n'.join(ocr_texts.values())
                            else:
                                combined = '\n'.join(texts.values())
                            d.ocr_text = combined
                            d.pages = len(texts) if texts else None
                            res = classifier.classify_document(d.filename, d.ocr_text)
                            d.document_type = res.document_type
                            sess.add(d)
                            ctx_log.info('OCR/classify complete for doc', extra={'doc_id': d.id, 'type': d.document_type})
                        except Exception as exc:
                            # mark app error and abort
                            d.ocr_text = None
                            sess.add(d)
                            app.last_error = f'OCR_FAILED: {str(exc)[:200]}'
                            app.state = State.ERROR.value
                            sess.add(app)
                            ctx_log.exception('OCR/classify failed for doc %s: %s', d.id, exc)
                            raise
                    # transition
                    machine = ApplicationStateMachine(sess)
                    machine.transition(app, State.DOCUMENTS_IDENTIFIED, reason='Documents classified')
                # commit
        except Exception as exc:
            logger.exception('Processing failed during OCR/classify for %s: %s', message_id, exc)
            return None

        # Verification
        try:
            with self.db.SessionLocal() as sess:
                with sess.begin():
                    app = sess.query(Application).filter(Application.message_id == message_id).first()
                    ctx_log = get_logger('tac.pipeline', processing_id=app.processing_id, message_id=message_id, application_id=app.id)
                    res = verification.verify_required_documents(app, sess)
                    if not res.ok:
                        machine = ApplicationStateMachine(sess)
                        machine.transition(app, State.MISSING_DOCUMENTS, reason=f'Missing: {res.missing}')
                        ctx_log.info('Verification failed, missing docs', extra={'missing': res.missing})
                        return app
                    else:
                        machine = ApplicationStateMachine(sess)
                        machine.transition(app, State.VERIFIED if res.ok and not res.issues else State.VERIFICATION_FAILED, reason='Verification complete')
                # commit
        except Exception as exc:
            logger.exception('Processing failed during verification for %s: %s', message_id, exc)
            return None

        # Packaging: create package file and ensure idempotency
        package_obj = None
        try:
            with self.db.SessionLocal() as sess:
                with sess.begin():
                    app = sess.query(Application).filter(Application.message_id == message_id).first()
                    ctx_log = get_logger('tac.pipeline', processing_id=app.processing_id, message_id=message_id, application_id=app.id)
                    # collect ordered paths
                    order = self.cfg.processing.get('package_order', [])
                    docs = sess.query(Document).filter(Document.application_id == app.id).all()
                    ordered_paths = []
                    for t in order:
                        for d in docs:
                            if d.document_type == t:
                                ordered_paths.append(d.path)
                    for d in docs:
                        if d.path not in ordered_paths:
                            ordered_paths.append(d.path)
                    if not ordered_paths:
                        ctx_log.warning('No documents to package', extra={})
                        return app
                    output_dir = Path(self.cfg.data_dir) / 'packages'
                    pkg_path = packager.create_package(app.id, ordered_paths, str(output_dir))
                    # idempotent insert
                    package_obj = self.enh.ensure_package_idempotent(sess, app, pkg_path)
                    machine = ApplicationStateMachine(sess)
                    machine.transition(app, State.PACKAGED, reason='Package created')
                # commit
        except Exception as exc:
            logger.exception('Processing failed during packaging for %s: %s', message_id, exc)
            # mark error
            try:
                with self.db.SessionLocal() as sess:
                    app = sess.query(Application).filter(Application.message_id == message_id).first()
                    if app:
                        app.last_error = f'PACKAGING_FAILED: {str(exc)[:200]}'
                        app.state = State.ERROR.value
                        sess.add(app)
                        sess.commit()
            except Exception:
                pass
            return None

        # Draft creation: idempotent
        try:
            with self.db.SessionLocal() as sess:
                with sess.begin():
                    app = sess.query(Application).filter(Application.message_id == message_id).first()
                    ctx_log = get_logger('tac.pipeline', processing_id=app.processing_id, message_id=message_id, application_id=app.id)
                    existing_draft = self.enh.ensure_draft_idempotent(sess, app)
                    if existing_draft:
                        ctx_log.info('Draft already exists; skipping creation', extra={'draft_id': existing_draft.draft_id})
                        return app
                    me = self.cfg.app.get('owner_email', None) or 'owner@example.com'
                    subject = f"Package for application {app.id}"
                    body = f"Please review package for application {app.id}"
                    # create draft via Gmail API
                    try:
                        draft_resp = self.create_draft(to=me, subject=subject, body=body, attachments=[package_obj.package_path if package_obj else ''])
                        dr = Draft(application_id=app.id, draft_id=draft_resp.get('id'), to=me, subject=subject, body=body)
                        sess.add(dr)
                        machine = ApplicationStateMachine(sess)
                        machine.transition(app, State.AWAITING_MY_APPROVAL, reason='Draft created')
                    except Exception as exc:
                        # record error and rethrow to outer handler
                        app.last_error = f'DRAFT_FAILED: {str(exc)[:200]}'
                        app.state = State.ERROR.value
                        sess.add(app)
                        ctx_log.exception('Draft creation failed: %s', exc)
                        raise
                # commit
        except Exception as exc:
            logger.exception('Processing failed during draft creation for %s: %s', message_id, exc)
            return None

        return app

    def create_draft(self, to: str, subject: str, body: str, attachments: Optional[List[str]] = None):
        if not self._service:
            raise RuntimeError('Gmail service not set')
        try:
            import mimetypes
            from email.message import EmailMessage
            import base64
            msg = EmailMessage()
            msg['To'] = to
            msg['Subject'] = subject
            msg.set_content(body)
            if attachments:
                for p in attachments:
                    if not p:
                        continue
                    ctype, _ = mimetypes.guess_type(p)
                    maintype, subtype = (ctype or 'application/octet-stream').split('/', 1)
                    with open(p, 'rb') as fh:
                        data = fh.read()
                    msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=Path(p).name)
            raw = base64.urlsafe_b64encode(msg.as_bytes()).decode('utf-8')
            resp = self._service.users().drafts().create(userId='me', body={'message': {'raw': raw}}).execute()
            return resp
        except Exception as exc:
            logger.exception('Failed to create draft: %s', exc)
            raise

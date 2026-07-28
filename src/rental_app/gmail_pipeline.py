from __future__ import annotations
from typing import List, Dict, Any, Optional
from pathlib import Path
import base64
import hashlib
import logging
import os
import tempfile

from rental_app.config import load_config
from rental_app.credential_store import CredentialStore
from rental_app.db import DB
from rental_app.models import EmailRecord, Document, Application, Package, Draft
from rental_app.state_machine import ApplicationStateMachine, State
from rental_app import ocr, classifier, verification, packager

logger = logging.getLogger(__name__)

# Lazy google imports
try:
    from googleapiclient.errors import HttpError  # type: ignore
except Exception:  # pragma: no cover
    HttpError = Exception


class GmailClient:
    """Gmail integration: end-to-end processing pipeline."""

    def __init__(self, credential_store: CredentialStore, db: Optional[DB] = None, config_path: Optional[str] = None):
        self.credential_store = credential_store
        self.cfg = load_config(config_path)
        self.db = db or DB(db_url=f"sqlite:///{self.cfg.db_path}")
        self._service = None

    def set_service(self, service_obj):
        self._service = service_obj

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
        from_hdr = None
        for h in headers:
            if h.get('name', '').lower() == 'from':
                from_hdr = h.get('value')
        subject = next((h.get('value') for h in headers if h.get('name','').lower()=='subject'), '')
        # parse sender email
        sender_email = ''
        if from_hdr and '@' in from_hdr:
            # simple parse
            if '<' in from_hdr and '>' in from_hdr:
                sender_email = from_hdr.split('<')[-1].split('>')[0].strip().lower()
            else:
                sender_email = from_hdr.strip().lower()
        approved = [e.lower() for e in self.cfg.approved_agents.get('emails', [])]
        with self.db.SessionLocal() as sess:
            # record email if missing
            existing_email = sess.query(EmailRecord).filter(EmailRecord.message_id == message_id).first()
            if not existing_email:
                er = EmailRecord(message_id=message_id, sender=from_hdr or '', sender_email=sender_email, subject=subject, raw_headers=headers, raw_payload=payload)
                sess.add(er)
                sess.flush()
            # check approved
            if sender_email not in approved:
                logger.info('Message %s from %s not approved; skipping', message_id, sender_email)
                sess.commit()
                return None
            # create or fetch application
            machine = ApplicationStateMachine(sess)
            app = machine.create_application_if_missing(message_id, history_id=msg.get('historyId'))
            sess.refresh(app)
            if app.state != State.NEW.value:
                logger.info('Application %s already processed to state %s; skipping download', app.id, app.state)
                return app
            # download attachments
            parts = payload.get('parts') or []
            attachments = []

            def walk(parts_list):
                for part in parts_list:
                    filename = part.get('filename')
                    body = part.get('body', {})
                    if filename and body.get('attachmentId'):
                        aid = body.get('attachmentId')
                        try:
                            att = self._service.users().messages().attachments().get(userId='me', messageId=message_id, id=aid).execute()
                            data = att.get('data')
                            if not data:
                                logger.warning('Attachment %s has no data', aid)
                                continue
                            raw = base64.urlsafe_b64decode(data.encode('utf-8'))
                            attach_dir = Path(self.cfg.data_dir) / 'attachments' / message_id
                            attach_dir.mkdir(parents=True, exist_ok=True)
                            checksum = hashlib.sha256(raw).hexdigest()
                            safe_name = f"{checksum[:16]}_{filename}"
                            dest = attach_dir / safe_name
                            if not dest.exists():
                                # atomic write
                                tmp = attach_dir / (safe_name + '.tmp')
                                with open(tmp, 'wb') as fh:
                                    fh.write(raw)
                                    fh.flush()
                                    os.fsync(fh.fileno())
                                os.replace(tmp, dest)
                            # save document record if not exists
                            exists = sess.query(Document).filter(Document.checksum == checksum, Document.application_id == app.id).first()
                            if not exists:
                                doc = Document(application_id=app.id, filename=filename, path=str(dest), checksum=checksum, size_bytes=len(raw))
                                sess.add(doc)
                                sess.flush()
                                attachments.append(doc)
                            else:
                                attachments.append(exists)
                        except Exception as exc:
                            logger.exception('Failed to download attachment %s: %s', aid, exc)
                    if part.get('parts'):
                        walk(part.get('parts'))

            walk(parts)
            # transition to DOWNLOADED
            machine.transition(app, State.DOWNLOADED, reason=f'Downloaded {len(attachments)} attachments')
            sess.commit()

        # After commit, perform OCR/classification and verification in a new session
        with self.db.SessionLocal() as sess:
            machine = ApplicationStateMachine(sess)
            app = machine.get_application_by_message_id(message_id)
            docs = sess.query(Document).filter(Document.application_id == app.id).all()
            # OCR and classify
            for d in docs:
                try:
                    # attempt to extract text via PDF text extraction
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
                    # classify
                    res = classifier.classify_document(d.filename, d.ocr_text)
                    d.document_type = res.document_type
                    sess.add(d)
                except Exception as exc:
                    logger.exception('Failed OCR/classify for doc %s: %s', d.id, exc)
            sess.flush()
            machine.transition(app, State.DOCUMENTS_IDENTIFIED, reason='Documents classified')
            sess.commit()

        # Verification
        with self.db.SessionLocal() as sess:
            machine = ApplicationStateMachine(sess)
            app = machine.get_application_by_message_id(message_id)
            res = verification.verify_required_documents(app, sess)
            if not res.ok:
                machine.transition(app, State.MISSING_DOCUMENTS, reason=f"Missing: {res.missing}")
                sess.commit()
                return app
            else:
                machine.transition(app, State.VERIFICATION_FAILED if res.issues else State.VERIFIED, reason='Verification complete')
                sess.commit()

        # Prepare package
        with self.db.SessionLocal() as sess:
            machine = ApplicationStateMachine(sess)
            app = machine.get_application_by_message_id(message_id)
            # gather documents in package order
            order = self.cfg.processing.get('package_order', [])
            docs = sess.query(Document).filter(Document.application_id == app.id).all()
            ordered_paths = []
            # add docs by type in order
            for t in order:
                for d in docs:
                    if d.document_type == t:
                        ordered_paths.append(d.path)
            # append any unknowns
            for d in docs:
                if d.path not in ordered_paths:
                    ordered_paths.append(d.path)
            if not ordered_paths:
                logger.warning('No documents to package for app %s', app.id)
                return app
            output_dir = Path(self.cfg.data_dir) / 'packages'
            pkg_path = packager.create_package(app.id, ordered_paths, str(output_dir))
            # compute checksum
            import hashlib
            with open(pkg_path, 'rb') as fh:
                chk = hashlib.sha256(fh.read()).hexdigest()
            p = Package(application_id=app.id, package_path=pkg_path, checksum=chk, metadata={})
            sess.add(p)
            sess.flush()
            machine.transition(app, State.PACKAGED, reason='Package created')
            sess.commit()

        # Create draft with package attached
        with self.db.SessionLocal() as sess:
            machine = ApplicationStateMachine(sess)
            app = machine.get_application_by_message_id(message_id)
            # draft to me
            me = self.cfg.app.get('owner_email', None) or 'owner@example.com'
            subject = f"Package for application {app.id}"
            body = f"Please review package for application {app.id}"
            try:
                draft_resp = self.create_draft(to=me, subject=subject, body=body, attachments=[p.package_path])
                dr = Draft(application_id=app.id, draft_id=draft_resp.get('id'), to=me, subject=subject, body=body)
                sess.add(dr)
                sess.commit()
                machine.transition(app, State.AWAITING_MY_APPROVAL, reason='Draft created')
                sess.commit()
            except Exception as exc:
                logger.exception('Failed to create draft: %s', exc)
                machine.transition(app, State.ERROR, reason='Draft creation failed')
                sess.commit()
        return app

    # create_draft is same as earlier implementation
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

from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from pathlib import Path
import base64
import hashlib
import logging
import os
import tempfile

from rental_app.config import load_config
from rental_app.credential_store import CredentialStore
from rental_app.db import DB
from rental_app.models import EmailRecord, Document, Application
from rental_app.state_machine import ApplicationStateMachine, State

logger = logging.getLogger(__name__)

# Lazy google imports
try:
    from googleapiclient.errors import HttpError  # type: ignore
except Exception:  # pragma: no cover
    HttpError = Exception


@dataclass
class PubSubMessage:
    message_id: str
    data: Dict[str, Any]
    ack_id: Optional[str] = None


class PubSubAdapterError(Exception):
    pass


class PubSubAdapter:
    """Abstract Pub/Sub adapter interface."""

    def pull_messages(self, max_messages: int = 10, timeout: int = 10) -> List[PubSubMessage]:
        raise NotImplementedError

    def ack(self, ack_id: str) -> None:
        raise NotImplementedError


class GmailClientError(Exception):
    pass


class GmailClient:
    """Gmail integration: Watch, History sync, and message processing."""

    def __init__(self, credential_store: CredentialStore, db: Optional[DB] = None, pubsub_adapter: Optional[PubSubAdapter] = None, config_path: Optional[str] = None):
        self.credential_store = credential_store
        self.cfg = load_config(config_path)
        self.db = db or DB(db_url=f"sqlite:///{self.cfg.db_path}")
        self.pubsub_adapter = pubsub_adapter
        self._service = None

    @property
    def service(self):
        return self._service

    def set_service(self, service_obj):
        """Set the underlying googleapiclient service (used in tests/mocks)."""
        self._service = service_obj

    def start_watch(self, topic_name: Optional[str] = None, label_filter: Optional[str] = None) -> Dict[str, Any]:
        """Register a Gmail watch for push notifications (requires Pub/Sub topic).

        Returns the watch response dict.
        """
        if not self._service:
            raise GmailClientError("Gmail service not authenticated")
        topic = topic_name or self.cfg.gmail.pubsub.get("topic_name")
        if not topic:
            raise GmailClientError("No Pub/Sub topic configured for Gmail watch")
        body = {"topicName": topic}
        if label_filter:
            body["labelIds"] = [label_filter]
        try:
            resp = self._service.users().watch(userId="me", body=body).execute()
            # persist watch metadata in checkpoints table
            with self.db.SessionLocal() as sess:
                sess.execute("INSERT OR REPLACE INTO checkpoints(key, value) VALUES (:k, :v)", {"k": "watch_response", "v": str(resp)})
                sess.commit()
            logger.info("Watch started: %s", resp)
            return resp
        except HttpError as e:
            logger.exception("Failed to start watch: %s", e)
            raise GmailClientError("Failed to start watch") from e

    def handle_pubsub_message(self, pubsub_raw: Dict[str, Any]) -> List[str]:
        """Handle an incoming Pub/Sub push payload and return list of message IDs to process.

        The pubsub_raw is the decoded JSON payload from Pub/Sub.
        """
        # Gmail push payload has 'historyId' field and 'emailAddress'
        history_id = None
        if isinstance(pubsub_raw, dict):
            history_id = pubsub_raw.get("historyId")
        if not history_id:
            logger.warning("Pub/Sub message did not contain historyId: %s", pubsub_raw)
            return []
        logger.info("Received pubsub historyId=%s", history_id)
        # sync history
        msg_ids = self.sync_history(history_id)
        return msg_ids

    def sync_history(self, start_history_id: Optional[str] = None) -> List[str]:
        """Use Gmail history.list to find changed message IDs since start_history_id.

        Returns unique list of message IDs to process.
        """
        if not self._service:
            raise GmailClientError("Gmail service not initialized")
        result_ids: List[str] = []
        try:
            request = self._service.users().history().list(userId="me", startHistoryId=start_history_id)
            while request:
                resp = request.execute()
                histories = resp.get("history", [])
                for h in histories:
                    messages = h.get("messages", [])
                    for m in messages:
                        mid = m.get("id")
                        if mid:
                            result_ids.append(mid)
                request = self._service.users().history().list_next(request, resp)
            # persist last_history_id
            with self.db.SessionLocal() as sess:
                sess.execute("INSERT OR REPLACE INTO checkpoints(key, value) VALUES (:k, :v)", {"k": "last_history_id", "v": str(start_history_id)})
                sess.commit()
            unique_ids = list(dict.fromkeys(result_ids))
            logger.info("History sync found %d message ids", len(unique_ids))
            return unique_ids
        except HttpError as e:
            # historyId expired or invalid; fallback to scanning unread
            logger.exception("History sync failed: %s", e)
            return self.scan_unread()
        except Exception as e:
            logger.exception("Unexpected error during history sync: %s", e)
            return self.scan_unread()

    def scan_unread(self) -> List[str]:
        """Fallback: scan unread messages in INBOX and return their IDs."""
        if not self._service:
            raise GmailClientError("Gmail service not initialized")
        try:
            resp = self._service.users().messages().list(userId="me", q="in:inbox is:unread").execute()
            messages = resp.get("messages", []) or []
            ids = [m.get("id") for m in messages if m.get("id")]
            logger.info("Scan unread found %d messages", len(ids))
            return ids
        except Exception as e:
            logger.exception("Failed to scan unread messages: %s", e)
            return []

    def _get_header_value(self, headers: List[Dict[str, str]], name: str) -> Optional[str]:
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
        """Process a single Gmail message id: fetch, filter, download attachments, and record.

        Returns the Application record or None if skipped.
        """
        if not self._service:
            raise GmailClientError("Gmail service not initialized")

        # fetch full message
        try:
            msg = self._service.users().messages().get(userId="me", id=message_id, format="full").execute()
        except HttpError as e:
            logger.exception("Failed to fetch message %s: %s", message_id, e)
            return None

        payload = msg.get("payload", {})
        headers = payload.get("headers", [])
        from_hdr = self._get_header_value(headers, "From")
        subject = self._get_header_value(headers, "Subject") or ""
        history_id = msg.get("historyId")
        name, email_addr = self._parse_sender(from_hdr)
        sender_email = (email_addr or name or "").lower()

        # get approved emails from config
        approved_emails = [e.lower() for e in self.cfg.approved_agents.get("emails", [])]
        if sender_email not in approved_emails:
            logger.info("Message %s from %s not in approved list; recording EmailRecord and skipping", message_id, sender_email)
            with self.db.SessionLocal() as sess:
                # record email if missing
                from sqlalchemy import select
                existing = sess.execute(select(EmailRecord).where(EmailRecord.message_id == message_id)).scalars().first()
                if not existing:
                    er = EmailRecord(message_id=message_id, sender=name or sender_email, sender_email=sender_email, subject=subject, raw_headers=headers, raw_payload=payload)
                    sess.add(er)
                    sess.commit()
            return None

        # proceed with processing
        with self.db.SessionLocal() as sess:
            machine = ApplicationStateMachine(sess)
            app = machine.create_application_if_missing(message_id, history_id=history_id)
            # if already downloaded or further, skip processing
            from sqlalchemy import select
            sess.refresh(app)
            if app.state != State.NEW.value:
                logger.info("Application %s already in state %s; skipping download", app.id, app.state)
                return app
            # traverse payload parts to find attachments
            parts = payload.get("parts") or []
            attachments_saved = []

            def walk(parts_list):
                for part in parts_list:
                    filename = part.get("filename")
                    body = part.get("body", {})
                    mime = part.get("mimeType")
                    if filename and body.get("attachmentId"):
                        att_id = body.get("attachmentId")
                        try:
                            att = self._service.users().messages().attachments().get(userId="me", messageId=message_id, id=att_id).execute()
                            data = att.get("data")
                            if data is None:
                                logger.warning("Attachment %s has no data", att_id)
                                continue
                            raw = base64.urlsafe_b64decode(data.encode("utf-8"))
                            # write atomically
                            attach_dir = Path(self.cfg.data_dir) / "attachments" / message_id
                            attach_dir.mkdir(parents=True, exist_ok=True)
                            checksum = hashlib.sha256(raw).hexdigest()
                            safe_name = f"{checksum[:16]}_{filename}"
                            tmpf = tempfile.NamedTemporaryFile(delete=False, dir=str(attach_dir))
                            try:
                                tmpf.write(raw)
                                tmpf.flush()
                                os.fsync(tmpf.fileno())
                                tmpf.close()
                                dest = attach_dir / safe_name
                                os.replace(tmpf.name, dest)
                            finally:
                                if os.path.exists(tmpf.name):
                                    try:
                                        os.unlink(tmpf.name)
                                    except Exception:
                                        pass
                            # record document if not exists
                            exists = sess.query(Document).filter_by(application_id=app.id, checksum=checksum).first()
                            if not exists:
                                doc = Document(application_id=app.id, filename=filename, path=str(dest), checksum=checksum, size_bytes=len(raw))
                                sess.add(doc)
                                sess.flush()
                            attachments_saved.append(str(dest))
                        except Exception as exc:
                            logger.exception("Failed to download attachment %s for message %s: %s", att_id, message_id, exc)
                    if part.get("parts"):
                        walk(part.get("parts"))

            walk(parts)
            # All attachments processed; transition state
            machine.transition(app, State.DOWNLOADED, reason=f"Downloaded {len(attachments_saved)} attachments")
            sess.commit()
            logger.info("Processed message %s and saved %d attachments", message_id, len(attachments_saved))
            return app

    def create_draft(self, to: str, subject: str, body: str, attachments: Optional[List[str]] = None) -> Dict[str, Any]:
        """Create a Gmail draft; attachments are paths to local files."""
        if not self._service:
            raise GmailClientError("Gmail service not initialized")
        try:
            import mimetypes
            from email.message import EmailMessage

            msg = EmailMessage()
            msg["To"] = to
            msg["Subject"] = subject
            msg.set_content(body)
            if attachments:
                for p in attachments:
                    ctype, _ = mimetypes.guess_type(p)
                    maintype, subtype = (ctype or "application/octet-stream").split("/", 1)
                    with open(p, "rb") as fh:
                        data = fh.read()
                    msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=Path(p).name)
            raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
            draft = {"message": {"raw": raw}}
            resp = self._service.users().drafts().create(userId="me", body=draft).execute()
            return resp
        except Exception as exc:
            logger.exception("Failed to create draft: %s", exc)
            raise GmailClientError("Failed to create draft") from exc

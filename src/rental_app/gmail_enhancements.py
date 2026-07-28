from __future__ import annotations
from typing import Optional, List
import logging
import traceback

from rental_app.config import load_config
from rental_app.credential_store import CredentialStore
from rental_app.db import DB
from rental_app.models import Document, Package, Draft, Application
from rental_app.state_machine import ApplicationStateMachine, State
from rental_app.logging_config import get_logger
from rental_app.checkpoints import set_checkpoint, get_checkpoint
from rental_app.utils import save_attachment_atomic, compute_checksum
from rental_app import packager

logger = logging.getLogger(__name__)


class GmailClientEnhancements:
    def __init__(self, credential_store: CredentialStore, db: Optional[DB] = None, config_path: Optional[str] = None):
        self.credential_store = credential_store
        self.cfg = load_config(config_path)
        self.db = db or DB(db_url=f"sqlite:///{self.cfg.db_path}")
        self._service = None

    def set_service(self, service):
        self._service = service

    def _record_error(self, sess, app: Application, code: str, exc: Exception):
        app.last_error = f"{code}: {str(exc)[:200]}"
        app.state = State.ERROR.value
        sess.add(app)
        sess.flush()
        logger.error("Application %s moved to ERROR: %s", app.id, app.last_error)

    def ensure_package_idempotent(self, sess, app: Application, package_path: str) -> Optional[Package]:
        # compute checksum
        import hashlib
        with open(package_path, 'rb') as fh:
            chk = hashlib.sha256(fh.read()).hexdigest()
        existing = sess.query(Package).filter(Package.application_id == app.id, Package.checksum == chk).first()
        if existing:
            # remove duplicate file
            try:
                os.remove(package_path)
            except Exception:
                pass
            return existing
        p = Package(application_id=app.id, package_path=package_path, checksum=chk, metadata={})
        sess.add(p)
        sess.flush()
        return p

    def ensure_draft_idempotent(self, sess, app: Application) -> Optional[Draft]:
        existing = sess.query(Draft).filter(Draft.application_id == app.id).first()
        return existing

    def renew_watch_if_needed(self):
        # check checkpoint and renew using Gmail API if expiration approaching
        from rental_app.gmail_watch import watch_needs_renewal, persist_watch_metadata
        if not self._service:
            logger.warning('Gmail service not set for watch renewal')
            return False
        db = self.db
        if not watch_needs_renewal(db):
            return False
        topic = self.cfg.gmail.pubsub.get('topic_name')
        if not topic:
            logger.warning('No pubsub topic configured; cannot renew watch')
            return False
        try:
            resp = self._service.users().watch(userId='me', body={'topicName': topic}).execute()
            # resp contains expirationTime and historyId perhaps
            resource_id = resp.get('historyId', None) or resp.get('pushToken', None) or resp.get('labelFilterAction', None)
            expiration = resp.get('expiration') or resp.get('expirationTime') or None
            expire_ts = None
            if expiration:
                try:
                    from dateutil import parser
                    dt = parser.parse(expiration)
                    expire_ts = int(dt.timestamp())
                except Exception:
                    pass
            persist_watch_metadata(db, resource_id, expire_ts or 0)
            logger.info('Watch renewed: %s', resp)
            return True
        except Exception as exc:
            logger.exception('Failed to renew watch: %s', exc)
            return False

    def handle_history_expired(self, start_history_id: str) -> List[str]:
        # fallback behavior: scan unread and log recovery
        logger.warning('History id %s expired, falling back to unread scan', start_history_id)
        # persist a checkpoint indicating recovery
        set_checkpoint(self.db, 'last_history_id', '')
        # perform unread scan using service
        try:
            resp = self._service.users().messages().list(userId='me', q='in:inbox is:unread').execute()
            messages = resp.get('messages', []) or []
            ids = [m.get('id') for m in messages if m.get('id')]
            logger.info('Recovery scan found %d messages', len(ids))
            return ids
        except Exception as exc:
            logger.exception('Failed to perform recovery scan: %s', exc)
            return []

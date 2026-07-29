#!/usr/bin/env python3
import os
import time
import signal
import sys
import logging
import shutil
import importlib
from pathlib import Path
from rental_app.config_env import get_config
from rental_app.db import DB
from rental_app.gmail_core import GmailClient
from rental_app.gmail_pipeline import GmailPipeline
from rental_app.gmail_enhancements import GmailClientEnhancements

LOG = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

POLL_INTERVAL = int(os.getenv('TAC_POLL_INTERVAL', '60'))  # seconds
LABEL_NAME = os.getenv('TAC_LABEL_NAME', 'New Apps')
REVIEWER_EMAIL = os.getenv('REVIEWER_EMAIL')  # required to send completed package to reviewer
DRY_RUN = os.getenv('DRY_RUN', '').lower() in ('1', 'true', 'yes')


class Worker:
    def __init__(self, cfg):
        self.cfg = cfg
        self.db = DB(db_url=cfg.db_url)
        self.gmail_client = GmailClient(credentials_path=cfg.gmail_credentials)
        self.pipeline = GmailPipeline(credential_store=None, db=self.db)
        self.enh = GmailClientEnhancements(credential_store=None, db=self.db)
        self._stop = False

    def authenticate(self):
        self.gmail_client.authenticate()
        svc = self.gmail_client.service
        self.pipeline.set_service(svc)
        self.enh.set_service(svc)

    def health_check(self):
        ok = True
        LOG.info("Performing startup health check...")
        # Gmail credentials file
        if not os.path.exists(self.cfg.gmail_credentials):
            LOG.warning("Gmail credentials file not found at %s", self.cfg.gmail_credentials)
        # DB check
        try:
            with self.db.engine.connect() as conn:
                conn.execute("SELECT 1")
            LOG.info("Database connection: OK")
        except Exception as e:
            LOG.exception("Database connection failed: %s", e)
            ok = False
        # data dir
        data_dir = Path(self.cfg.data_dir)
        try:
            data_dir.mkdir(parents=True, exist_ok=True)
            LOG.info("Data dir: %s", data_dir)
        except Exception as e:
            LOG.exception("Data dir check failed: %s", e)
            ok = False
        # tesseract check
        if shutil.which('tesseract'):
            LOG.info("Tesseract: found")
        else:
            LOG.warning("Tesseract: not found; OCR of scanned PDFs will not work until tesseract is installed")
        # dependencies
        for mod in ('pypdf', 'fitz', 'pytesseract'):
            try:
                importlib.import_module(mod)
                LOG.info("Dependency '%s': OK", mod)
            except Exception as ex:
                LOG.warning("Dependency '%s' not available: %s", mod, ex)
        LOG.info("Startup health check complete. Mode=%s", "POLLING" if not os.getenv('GMAIL_PUBSUB_TOPIC') else "WATCH")
        return ok

    def handle_message(self, message_id: str):
        LOG.info("Processing message %s", message_id)
        try:
            app = self.pipeline.process_message(message_id)
            if app:
                from rental_app.state_machine import State
                from rental_app.models import Package
                with self.db.SessionLocal() as sess:
                    sess.refresh(app)
                    pkgs = sess.query(Package).filter(Package.application_id == app.id).all()
                    if pkgs and app.state in (State.PACKAGED.value, State.AWAITING_MY_APPROVAL.value):
                        latest_pkg = sorted(pkgs, key=lambda p: p.created_at)[-1]
                        self.send_package_to_reviewer(app, latest_pkg.package_path)
                    elif app.state == State.MISSING_DOCUMENTS.value:
                        LOG.info("Application %s missing documents; draft should exist (not sent)", app.id)
        except Exception:
            LOG.exception("Failed to process message %s", message_id)

    def send_package_to_reviewer(self, app, package_path: str):
        global DRY_RUN
        if not REVIEWER_EMAIL:
            LOG.warning("REVIEWER_EMAIL is not configured; skipping send")
            return
        subject = f"Review package for application {app.id}"
        body = f"Applicant: {app.email_record.sender if app.email_record else 'unknown'}\nApplication id: {app.id}\nState: {app.state}\n"
        LOG.info("Preparing to send package %s to reviewer %s", package_path, REVIEWER_EMAIL)
        if DRY_RUN:
            LOG.info("DRY_RUN enabled: would send package %s to %s (not sending)", package_path, REVIEWER_EMAIL)
            return
        try:
            resp = self.pipeline.create_draft(to=REVIEWER_EMAIL, subject=subject, body=body, attachments=[package_path])
            draft_id = resp.get('id')
            if draft_id:
                self.gmail_client.send_draft(draft_id)
                LOG.info("Sent package %s to reviewer %s via Gmail draft %s", package_path, REVIEWER_EMAIL, draft_id)
        except Exception:
            LOG.exception("Failed to send package to reviewer for app %s", app.id)

    def poll_label(self):
        LOG.info("Polling label %s for new messages", LABEL_NAME)
        label_id = None
        try:
            label_id = self.gmail_client.get_label_id(LABEL_NAME)
        except Exception:
            LOG.exception("Error getting label id; continuing with None")
        msgs = self.gmail_client.list_messages(label_ids=[label_id] if label_id else None, q=None)
        for m in msgs:
            mid = m.get('id')
            from rental_app.models import EmailRecord
            with self.db.SessionLocal() as sess:
                existing = sess.query(EmailRecord).filter(EmailRecord.message_id == mid).first()
                if existing:
                    continue
            self.handle_message(mid)

    def run(self):
        self.authenticate()
        ok = self.health_check()
        if not ok:
            LOG.warning("Startup health check had warnings/errors. Continuing but inspect logs.")
        LOG.info("Worker started (poll interval=%s) DRY_RUN=%s", POLL_INTERVAL, DRY_RUN)
        while not self._stop:
            try:
                topic = os.getenv('GMAIL_PUBSUB_TOPIC')
                if topic:
                    try:
                        label_id = self.gmail_client.get_label_id(LABEL_NAME)
                        if label_id:
                            resp = self.gmail_client.watch(topic_name=topic, label_ids=[label_id])
                            LOG.info("Registered watch: %s", resp)
                    except Exception:
                        LOG.exception("Watch registration failed; will fallback to polling")
                self.poll_label()
            except Exception:
                LOG.exception("Worker loop error")
            time.sleep(POLL_INTERVAL)

    def stop(self):
        self._stop = True


def main():
    cfg = get_config()
    worker = Worker(cfg)
    def _stop(signum, frame):
        LOG.info("Received signal %s; stopping worker", signum)
        worker.stop()
    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    worker.run()

if __name__ == '__main__':
    main()

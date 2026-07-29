from __future__ import annotations
import os
import json
import logging
from typing import Optional, List, Dict
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

LOG = logging.getLogger(__name__)

SCOPES = [
    'https://www.googleapis.com/auth/gmail.modify',
    'https://www.googleapis.com/auth/gmail.compose',
    'https://www.googleapis.com/auth/gmail.send',
]

TOKEN_PATH = os.getenv('GMAIL_TOKEN_PATH', './config/token.json')
CREDENTIALS_PATH = os.getenv('GMAIL_CREDENTIALS_PATH', './config/credentials.json')


class GmailClient:
    def __init__(self, credentials_path: Optional[str] = None, token_path: Optional[str] = None):
        self.credentials_path = credentials_path or CREDENTIALS_PATH
        self.token_path = token_path or TOKEN_PATH
        self.creds: Optional[Credentials] = None
        self.service = None

    def authenticate(self) -> None:
        """Run InstalledAppFlow if necessary and build service."""
        creds = None
        if os.path.exists(self.token_path):
            try:
                creds = Credentials.from_authorized_user_file(self.token_path, SCOPES)
            except Exception:
                LOG.exception("Failed to load token.json; will re-auth")
                creds = None
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                except Exception:
                    creds = None
            if not creds:
                if not os.path.exists(self.credentials_path):
                    raise FileNotFoundError(f"OAuth credentials not found at {self.credentials_path}")
                flow = InstalledAppFlow.from_client_secrets_file(self.credentials_path, SCOPES)
                creds = flow.run_local_server(port=0)
            # save the token
            with open(self.token_path, 'w') as fh:
                fh.write(creds.to_json())
        self.creds = creds
        self.service = build('gmail', 'v1', credentials=self.creds, cache_discovery=False)
        LOG.info("Gmail service built and authenticated")

    def get_label_id(self, label_name: str) -> Optional[str]:
        """Return the Gmail label ID for a given label name, or None if not found."""
        if not self.service:
            raise RuntimeError("Gmail service not initialized")
        labels = self.service.users().labels().list(userId='me').execute().get('labels', [])
        for l in labels:
            if l.get('name') == label_name:
                return l.get('id')
        return None

    def list_messages(self, label_ids: Optional[List[str]] = None, q: Optional[str] = None) -> List[Dict]:
        if not self.service:
            raise RuntimeError("Gmail service not initialized")
        msgs = []
        req = self.service.users().messages().list(userId='me', labelIds=label_ids or [], q=q)
        while req:
            resp = req.execute()
            for m in resp.get('messages', []) or []:
                msgs.append(m)
            req = self.service.users().messages().list_next(req, resp)
        return msgs

    def get_message(self, message_id: str, fmt: str = 'full') -> Dict:
        if not self.service:
            raise RuntimeError("Gmail service not initialized")
        return self.service.users().messages().get(userId='me', id=message_id, format=fmt).execute()

    def get_attachment(self, message_id: str, attachment_id: str) -> Dict:
        if not self.service:
            raise RuntimeError("Gmail service not initialized")
        return self.service.users().messages().attachments().get(userId='me', messageId=message_id, id=attachment_id).execute()

    def create_draft(self, raw_message: Dict) -> Dict:
        if not self.service:
            raise RuntimeError("Gmail service not initialized")
        return self.service.users().drafts().create(userId='me', body={'message': raw_message}).execute()

    def send_draft(self, draft_id: str) -> Dict:
        if not self.service:
            raise RuntimeError("Gmail service not initialized")
        return self.service.users().drafts().send(userId='me', body={'id': draft_id}).execute()

    def send_message_raw(self, raw_message: Dict) -> Dict:
        if not self.service:
            raise RuntimeError("Gmail service not initialized")
        return self.service.users().messages().send(userId='me', body={'raw': raw_message}).execute()

    def watch(self, topic_name: str, label_ids: Optional[List[str]] = None) -> Dict:
        if not self.service:
            raise RuntimeError("Gmail service not initialized")
        body = {'topicName': topic_name}
        if label_ids:
            body['labelIds'] = label_ids
        return self.service.users().watch(userId='me', body=body).execute()

    def stop_watch(self) -> Dict:
        if not self.service:
            raise RuntimeError("Gmail service not initialized")
        return self.service.users().stop(userId='me').execute()

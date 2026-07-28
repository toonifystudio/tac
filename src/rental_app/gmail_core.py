from __future__ import annotations
from typing import Optional
import json
import logging
from pathlib import Path

from rental_app.config import load_config
from rental_app.credential_store import CredentialStore, CredentialStoreError

logger = logging.getLogger(__name__)

# Lazy imports for Google libraries
try:
    from google.auth.transport.requests import Request  # type: ignore
    from google.oauth2.credentials import Credentials  # type: ignore
    from google_auth_oauthlib.flow import InstalledAppFlow  # type: ignore
    from googleapiclient.discovery import build  # type: ignore
except Exception:  # pragma: no cover
    Request = None
    Credentials = None
    InstalledAppFlow = None
    build = None

SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.compose",
]


class GmailClientError(Exception):
    """Generic Gmail client error."""


class GmailClient:
    """Minimal Gmail client for authentication.

    This class focuses on authentication and building a service client. Other
    operations (watch, history, processing) will be added in subsequent commits.
    """

    def __init__(self, credential_store: CredentialStore, config_path: Optional[str] = None):
        self.credential_store = credential_store
        self.cfg = load_config(config_path)
        self.credentials_path = Path(self.cfg.gmail.credentials_path) if getattr(self.cfg, 'gmail', None) else None
        self._service = None
        self._account_email = None

    @property
    def service(self):
        return self._service

    def authenticate(self, token_key: str = "tac_default") -> str:
        """Authenticate with Gmail and persist token via CredentialStore.

        :param token_key: fallback key under which a temporary token might be stored
        :return: authenticated account email
        :raises GmailClientError: on failures or missing libraries
        """
        if Credentials is None or InstalledAppFlow is None or build is None or Request is None:
            logger.error("Google libraries not installed")
            raise GmailClientError("Google libraries are not installed. Please install google-auth-oauthlib and google-api-python-client")

        creds = None

        # Try load token by token_key
        try:
            token_json = self.credential_store.load(token_key)
        except CredentialStoreError as exc:
            logger.warning("Credential store read failed for key %s: %s", token_key, exc)
            token_json = None

        if token_json:
            try:
                info = json.loads(token_json)
                creds = Credentials.from_authorized_user_info(info, SCOPES)  # type: ignore[arg-type]
            except Exception as exc:
                logger.exception("Failed to load credentials from token: %s", exc)
                creds = None

        # Refresh if expired and refresh_token present
        try:
            if creds and getattr(creds, 'expired', False) and getattr(creds, 'refresh_token', None):
                creds.refresh(Request())
        except Exception:
            creds = None

        if not creds or not getattr(creds, 'valid', False):
            # Run OAuth flow using client secrets
            if not self.credentials_path or not self.credentials_path.exists():
                logger.error("Credentials file missing at %s", self.credentials_path)
                raise GmailClientError(f"Credentials file not found at {self.credentials_path}")
            try:
                flow = InstalledAppFlow.from_client_secrets_file(str(self.credentials_path), SCOPES)
                creds = flow.run_local_server(port=0)
            except Exception as exc:
                logger.exception("OAuth flow failed: %s", exc)
                raise GmailClientError("OAuth authentication failed") from exc

        try:
            service = build('gmail', 'v1', credentials=creds, cache_discovery=False)
            profile = service.users().getProfile(userId='me').execute()
            account_email = profile.get('emailAddress') or token_key
            self._service = service
            self._account_email = account_email
            # Persist token under account_email
            try:
                token_to_store = creds.to_json()
                self.credential_store.save(account_email, token_to_store)
                # remove temporary token if different
                if token_key != account_email:
                    try:
                        self.credential_store.delete(token_key)
                    except Exception:
                        pass
            except CredentialStoreError as exc:
                logger.warning("Failed to save token for %s: %s", account_email, exc)
            logger.info("Authenticated %s", account_email)
            return account_email
        except Exception as exc:
            logger.exception("Failed to initialize Gmail service: %s", exc)
            raise GmailClientError("Failed to initialize Gmail service") from exc

    def close(self) -> None:
        self._service = None
        logger.debug("GmailClient closed")

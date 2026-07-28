from __future__ import annotations
from typing import Optional
from abc import ABC, abstractmethod
import logging

logger = logging.getLogger(__name__)


class CredentialStoreError(Exception):
    """Credential storage error."""


class CredentialStore(ABC):
    """Abstract credential storage interface."""

    @abstractmethod
    def save(self, account_id: str, token_json: str) -> None:
        """Save token JSON for account_id."""

    @abstractmethod
    def load(self, account_id: str) -> Optional[str]:
        """Load token JSON for account_id or return None."""

    @abstractmethod
    def delete(self, account_id: str) -> None:
        """Delete stored token for account_id."""


# Keyring implementation
try:
    import keyring  # type: ignore
except Exception:  # pragma: no cover - import guard
    keyring = None


class KeyringCredentialStore(CredentialStore):
    """Store token JSON in OS keyring using python-keyring."""

    SERVICE_NAME = "tac_tokens"

    def __init__(self, service_name: str = SERVICE_NAME):
        if keyring is None:
            raise CredentialStoreError("python-keyring is not available")
        self.service_name = service_name

    def save(self, account_id: str, token_json: str) -> None:
        try:
            keyring.set_password(self.service_name, account_id, token_json)
        except Exception as exc:
            logger.exception("Failed to save token: %s", exc)
            raise CredentialStoreError("Failed to save token") from exc

    def load(self, account_id: str) -> Optional[str]:
        try:
            return keyring.get_password(self.service_name, account_id)
        except Exception as exc:
            logger.exception("Failed to load token: %s", exc)
            raise CredentialStoreError("Failed to load token") from exc

    def delete(self, account_id: str) -> None:
        try:
            keyring.delete_password(self.service_name, account_id)
        except Exception:
            # ignore
            pass


# File encrypted store (requires cryptography)
try:
    from cryptography.fernet import Fernet, InvalidToken  # type: ignore
except Exception:  # pragma: no cover - import guard
    Fernet = None
    InvalidToken = Exception


class FileEncryptedCredentialStore(CredentialStore):
    """Store encrypted token JSON in local files using Fernet."""

    def __init__(self, base_dir: str, key: bytes):
        if Fernet is None:
            raise CredentialStoreError("cryptography.Fernet not available")
        import os
        os.makedirs(base_dir, exist_ok=True)
        self.base_dir = base_dir
        self.fernet = Fernet(key)

    def _path(self, account_id: str) -> str:
        safe = account_id.replace('/', '_')
        return f"{self.base_dir}/{safe}.token.enc"

    def save(self, account_id: str, token_json: str) -> None:
        path = self._path(account_id)
        token = token_json.encode('utf-8')
        data = self.fernet.encrypt(token)
        with open(path, 'wb') as fh:
            fh.write(data)

    def load(self, account_id: str) -> Optional[str]:
        path = self._path(account_id)
        try:
            with open(path, 'rb') as fh:
                data = fh.read()
            dec = self.fernet.decrypt(data)
            return dec.decode('utf-8')
        except FileNotFoundError:
            return None
        except InvalidToken as exc:
            logger.exception('Invalid encryption key: %s', exc)
            raise CredentialStoreError('Invalid encryption key') from exc

    def delete(self, account_id: str) -> None:
        import os
        try:
            os.remove(self._path(account_id))
        except Exception:
            pass

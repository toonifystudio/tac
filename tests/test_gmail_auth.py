import json
from unittest.mock import MagicMock, patch

import pytest

from rental_app.credential_store import KeyringCredentialStore, CredentialStore
from rental_app.gmail_core import GmailClient, GmailClientError


class DummyStore(CredentialStore):
    def __init__(self):
        self._d = {}

    def save(self, account_id: str, token_json: str) -> None:
        self._d[account_id] = token_json

    def load(self, account_id: str) -> str | None:
        return self._d.get(account_id)

    def delete(self, account_id: str) -> None:
        self._d.pop(account_id, None)


@patch('rental_app.gmail_core.build')
@patch('rental_app.gmail_core.InstalledAppFlow')
def test_authenticate_runs_oauth_when_no_token(MockFlow, MockBuild, tmp_path, monkeypatch):
    store = DummyStore()
    client = GmailClient(credential_store=store, config_path=None)

    mock_creds = MagicMock()
    mock_creds.to_json.return_value = json.dumps({"token": "x"})
    mock_creds.valid = True

    mock_flow = MagicMock()
    mock_flow.run_local_server.return_value = mock_creds
    MockFlow.from_client_secrets_file.return_value = mock_flow

    fake_service = MagicMock()
    fake_service.users.return_value.getProfile.return_value.execute.return_value = {"emailAddress": "u@example.com"}
    MockBuild.return_value = fake_service

    # monkeypatch credentials file location to a temp file
    cfg_path = tmp_path / 'config.yaml'
    cfg_path.write_text('gmail:\n  credentials_path: "./config/credentials.json"\n')
    monkeypatch.setenv('TAC_CONFIG_PATH', str(cfg_path))

    account = client.authenticate(token_key='tmpkey')
    assert account == 'u@example.com'
    assert store.load('u@example.com') is not None


@patch('rental_app.gmail_core.build')
@patch('rental_app.gmail_core.Credentials')
def test_authenticate_uses_existing_token(MockCredentials, MockBuild, tmp_path, monkeypatch):
    store = DummyStore()
    sample = json.dumps({"access_token": "a", "refresh_token": "r"})
    store.save('tmpkey', sample)
    MockCredentials.from_authorized_user_info.return_value = MagicMock(valid=True)

    fake_service = MagicMock()
    fake_service.users.return_value.getProfile.return_value.execute.return_value = {"emailAddress": "stored@example.com"}
    MockBuild.return_value = fake_service

    cfg_path = tmp_path / 'config.yaml'
    cfg_path.write_text('gmail:\n  credentials_path: "./config/credentials.json"\n')
    monkeypatch.setenv('TAC_CONFIG_PATH', str(cfg_path))

    client = GmailClient(credential_store=store, config_path=None)
    account = client.authenticate(token_key='tmpkey')
    assert account == 'stored@example.com'

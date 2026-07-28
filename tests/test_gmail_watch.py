from unittest.mock import MagicMock, patch
import json

from rental_app.gmail_client import GmailClient
from rental_app.credential_store import KeyringCredentialStore


@patch('rental_app.gmail_client.build')
def test_start_watch(MockBuild, tmp_path, monkeypatch):
    store = MagicMock(spec=KeyringCredentialStore)
    client = GmailClient(credential_store=store, config_path=None)
    # mock service
    fake_service = MagicMock()
    fake_service.users.return_value.watch.return_value.execute.return_value = {"watch": "ok"}
    client.set_service(fake_service)
    # monkeypatch cfg
    client.cfg.gmail.pubsub['topic_name'] = 'projects/x/topics/t'
    resp = client.start_watch()
    assert resp.get('watch') == 'ok'


@patch('rental_app.gmail_client.build')
def test_sync_history_fallback(MockBuild):
    store = MagicMock(spec=KeyringCredentialStore)
    client = GmailClient(credential_store=store, config_path=None)
    fake_service = MagicMock()
    # simulate history API raising HttpError
    fake_service.users.return_value.history.return_value.list.side_effect = Exception('history expired')
    fake_service.users.return_value.messages.return_value.list.return_value.execute.return_value = {'messages': [{'id': 'm1'}]}
    client.set_service(fake_service)
    ids = client.sync_history('123')
    assert ids == ['m1']

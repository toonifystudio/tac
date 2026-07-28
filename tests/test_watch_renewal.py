from unittest.mock import MagicMock, patch
from rental_app.gmail_enhancements import GmailClientEnhancements
from rental_app.db import DB
from rental_app.models import Base
import pytest


def test_watch_renewal_attempt(tmp_path, monkeypatch):
    db_path = tmp_path / "tac.db"
    db = DB(db_url=f"sqlite:///{db_path}")
    Base.metadata.create_all(db.engine)
    fake_service = MagicMock()
    fake_service.users.return_value.watch.return_value.execute.return_value = {'historyId': 'h123', 'expiration': None}
    client = GmailClientEnhancements(credential_store=MagicMock(), db=db)
    client.set_service(fake_service)
    client.cfg.gmail['pubsub'] = {'topic_name': 'projects/x/topics/t'}
    # force renewal
    monkeypatch.setattr('rental_app.gmail_watch.watch_needs_renewal', lambda db: True)
    res = client.renew_watch_if_needed()
    assert res is True


def test_handle_history_expired_fallback(tmp_path):
    db_path = tmp_path / "tac.db"
    db = DB(db_url=f"sqlite:///{db_path}")
    Base.metadata.create_all(db.engine)
    fake_service = MagicMock()
    fake_service.users.return_value.messages.return_value.list.return_value.execute.return_value = {'messages': [{'id': 'm1'}]}
    client = GmailClientEnhancements(credential_store=MagicMock(), db=db)
    client.set_service(fake_service)
    ids = client.handle_history_expired('123')
    assert ids == ['m1']

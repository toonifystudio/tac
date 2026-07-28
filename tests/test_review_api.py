from unittest.mock import MagicMock, patch
import base64
from rental_app.web import app
from rental_app.db import DB
from rental_app.models import Base, Application, Draft
from rental_app.credential_store import KeyringCredentialStore
import json
import tempfile


def setup_db(tmp_path):
    db_path = tmp_path / "tac.db"
    db = DB(db_url=f"sqlite:///{db_path}")
    Base.metadata.create_all(db.engine)
    return db


def make_app_client(tmp_path):
    client = app.test_client()
    return client


def test_dashboard_list_and_detail(tmp_path, monkeypatch):
    db = setup_db(tmp_path)
    # create a sample app record
    with db.SessionLocal() as sess:
        a = Application(message_id='m1', processing_id='p1', state='Awaiting My Approval')
        sess.add(a)
        sess.commit()
        aid = a.id
    client = make_app_client(tmp_path)
    rv = client.get('/api/applications')
    assert rv.status_code == 200
    data = rv.get_json()
    assert any(d['message_id'] == 'm1' for d in data)
    # detail
    rv2 = client.get(f'/api/applications/{aid}')
    assert rv2.status_code == 200
    jd = rv2.get_json()
    assert jd['message_id'] == 'm1'


def test_approve_and_send_draft(tmp_path, monkeypatch):
    db = setup_db(tmp_path)
    with db.SessionLocal() as sess:
        a = Application(message_id='m2', processing_id='p2', state='Awaiting My Approval')
        sess.add(a)
        sess.commit()
        aid = a.id
        d = Draft(application_id=aid, draft_id='draft-1', to='owner@example.com', subject='s', body='b')
        sess.add(d)
        sess.commit()
    client = make_app_client(tmp_path)
    # monkeypatch gmail send
    monkeypatch.setattr('rental_app.web._gmail', MagicMock())
    monkeypatch.getattr('rental_app.web._gmail')._service = MagicMock()
    monkeypatch.getattr('rental_app.web._gmail')._service.users.return_value.drafts.return_value.send.return_value.execute.return_value = {'id':'sent-1'}

    rv = client.post(f'/api/applications/{aid}/approve')
    assert rv.status_code == 200
    with db.SessionLocal() as sess:
        a = sess.query(Application).filter(Application.id == aid).first()
        assert a.state == 'Approved'


def test_reject_application(tmp_path):
    db = setup_db(tmp_path)
    with db.SessionLocal() as sess:
        a = Application(message_id='m3', processing_id='p3', state='Awaiting My Approval')
        sess.add(a)
        sess.commit()
        aid = a.id
    client = make_app_client(tmp_path)
    rv = client.post(f'/api/applications/{aid}/reject', json={'reason':'bad docs'})
    assert rv.status_code == 200
    with db.SessionLocal() as sess:
        a = sess.query(Application).filter(Application.id == aid).first()
        assert a.state == 'Error'

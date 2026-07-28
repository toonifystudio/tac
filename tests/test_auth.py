from unittest.mock import MagicMock
from rental_app.web import app
import os
import tempfile


def test_auth_protected(tmp_path, monkeypatch):
    # Ensure admin env vars
    monkeypatch.setenv('TAC_ADMIN_USER', 'admin')
    monkeypatch.setenv('TAC_ADMIN_PASS', 'pass')
    client = app.test_client()
    # Protected route should redirect to login
    rv = client.get('/api/applications')
    assert rv.status_code in (302,401)

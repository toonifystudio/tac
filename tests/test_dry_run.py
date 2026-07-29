import os
import pytest
from unittest.mock import MagicMock
from scripts.worker import Worker
from rental_app.config_env import get_config


def test_dry_run_prevents_send(monkeypatch, tmp_path):
    # configure env
    monkeypatch.setenv('DRY_RUN', 'true')
    cfg = get_config()
    w = Worker(cfg)
    # replace pipeline and gmail_client with mocks
    class FakePipeline:
        def create_draft(self, to, subject, body, attachments=None):
            return {'id': 'd1'}
    class FakeGmailClient:
        def send_draft(self, draft_id):
            raise RuntimeError('should not be called in DRY_RUN')
    w.pipeline = FakePipeline()
    w.gmail_client = FakeGmailClient()
    # call send_package_to_reviewer with DRY_RUN true
    os.environ['DRY_RUN'] = 'true'
    # should not raise
    w.send_package_to_reviewer(MagicMock(), str(tmp_path / 'pkg.pdf'))


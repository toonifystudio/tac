from __future__ import annotations
import os
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

class AppConfig:
    def __init__(self):
        self.db_url = os.getenv('TAC_DB', 'sqlite:///./data/tac.db')
        self.data_dir = os.getenv('TAC_DATA_DIR', './data')
        self.gmail_credentials = os.getenv('GMAIL_CREDENTIALS_PATH', './config/credentials.json')
        self.admin_user = os.getenv('TAC_ADMIN_USER', 'admin')
        self.admin_pass = os.getenv('TAC_ADMIN_PASS', 'password')
        self.secret_key = os.getenv('TAC_SECRET_KEY', 'dev-secret')
        self.demo_mode = os.getenv('TAC_DEMO_MODE', 'false').lower() in ('1','true','yes')
        self.json_log_file = os.getenv('TAC_JSON_LOG', './logs/tac.json')


_app_config: Optional[AppConfig] = None


def get_config() -> AppConfig:
    global _app_config
    if not _app_config:
        _app_config = AppConfig()
    return _app_config

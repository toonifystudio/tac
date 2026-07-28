from __future__ import annotations
import os
import yaml
from dataclasses import dataclass
from typing import List, Optional

DEFAULT_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "default.yaml")


@dataclass
class GmailConfig:
    credentials_path: str
    token_path: str


@dataclass
class AppConfig:
    data_dir: str
    db_path: str
    approved_agents: dict
    gmail: GmailConfig
    logging: dict
    processing: dict


def load_config(path: Optional[str] = None) -> AppConfig:
    """Load YAML configuration and return an AppConfig dataclass.

    :param path: Optional path to a YAML config file. If None, uses default.
    :return: AppConfig
    """
    p = path or os.getenv("TAC_CONFIG_PATH") or DEFAULT_CONFIG_PATH
    with open(p, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    app = raw.get("app", {})
    gmail_raw = raw.get("gmail", {})
    gmail = GmailConfig(
        credentials_path=gmail_raw.get("credentials_path", ""),
        token_path=gmail_raw.get("token_file_path", ""),
    )
    return AppConfig(
        data_dir=app.get("data_dir", "./data"),
        db_path=app.get("db_path", "./data/tac.db"),
        approved_agents=app.get("approved_agents", {}),
        gmail=gmail,
        logging=raw.get("logging", {}),
        processing=raw.get("processing", {}),
    )

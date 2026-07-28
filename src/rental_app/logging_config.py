import logging
import json
from typing import Optional
from logging.handlers import RotatingFileHandler


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        # Build a dict from record
        record_dict = {
            "name": record.name,
            "level": record.levelname,
            "message": record.getMessage(),
        }
        # include any extras
        if hasattr(record, "extra") and isinstance(record.extra, dict):
            record_dict.update(record.extra)
        # include exception info
        if record.exc_info:
            record_dict["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(record_dict)


def setup_logging(level: str = "INFO", json_log_file: Optional[str] = None) -> None:
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    # console handler
    ch = logging.StreamHandler()
    ch.setLevel(getattr(logging, level.upper(), logging.INFO))
    ch.setFormatter(JSONFormatter())
    root.addHandler(ch)
    # optional rotating file handler
    if json_log_file:
        fh = RotatingFileHandler(json_log_file, maxBytes=10 * 1024 * 1024, backupCount=5)
        fh.setLevel(getattr(logging, level.upper(), logging.INFO))
        fh.setFormatter(JSONFormatter())
        root.addHandler(fh)


class ContextLogger(logging.LoggerAdapter):
    def __init__(self, logger: logging.Logger, extra: Optional[dict] = None):
        super().__init__(logger, {})
        self._extra = extra or {}

    def process(self, msg, kwargs):
        extra = kwargs.get("extra", {})
        combined = {**self._extra, **extra}
        kwargs["extra"] = {"extra": combined}
        return msg, kwargs


def get_logger(name: str, processing_id: Optional[str] = None, message_id: Optional[str] = None, application_id: Optional[int] = None) -> ContextLogger:
    base = logging.getLogger(name)
    extras = {}
    if processing_id:
        extras["processing_id"] = processing_id
    if message_id:
        extras["message_id"] = message_id
    if application_id:
        extras["application_id"] = application_id
    return ContextLogger(base, extras)

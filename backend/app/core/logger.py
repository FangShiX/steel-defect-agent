import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from app.config.settings import settings


LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s:%(funcName)s:%(lineno)d | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_initialized = False


def _backend_dir() -> Path:
    return Path(__file__).resolve().parents[2]


def setup_logging() -> None:
    global _initialized
    if _initialized:
        return

    log_dir = _backend_dir() / settings.LOG_DIR
    log_dir.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO))
    root_logger.handlers.clear()

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    file_handler = RotatingFileHandler(
        filename=log_dir / "app.log",
        maxBytes=settings.LOG_MAX_BYTES,
        backupCount=settings.LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    for noisy_logger in (
        "uvicorn", "uvicorn.access", "sqlalchemy", "sqlalchemy.engine",
        "sqlalchemy.pool", "sqlalchemy.orm", "minio", "httpx",
    ):
        logging.getLogger(noisy_logger).setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").disabled = True

    _initialized = True


def get_logger(name: str) -> logging.Logger:
    setup_logging()
    return logging.getLogger(name)

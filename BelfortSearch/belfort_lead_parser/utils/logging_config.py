"""Настройка журналирования. Логи пишутся в файл и в консоль, без секретов."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from config import settings

_LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    """Инициализирует корневой логгер один раз и возвращает логгер приложения."""
    settings.ensure_dirs()
    root = logging.getLogger()

    if not root.handlers:
        root.setLevel(level)
        formatter = logging.Formatter(_LOG_FORMAT)

        file_handler = RotatingFileHandler(
            settings.LOG_PATH, maxBytes=2_000_000, backupCount=3, encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)

        console = logging.StreamHandler()
        console.setFormatter(formatter)
        root.addHandler(console)

    return logging.getLogger("belfort")

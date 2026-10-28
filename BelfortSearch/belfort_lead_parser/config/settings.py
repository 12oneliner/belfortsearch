"""Централизованная конфигурация приложения Belfort Lead Parser."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# Корень проекта: belfort_lead_parser/
PROJECT_ROOT = Path(__file__).resolve().parent.parent

DATA_DIR = Path(os.environ.get("BELFORT_DATA_DIR", PROJECT_ROOT / "data"))
LOGS_DIR = Path(os.environ.get("BELFORT_LOGS_DIR", PROJECT_ROOT / "logs"))
EXPORTS_DIR = Path(os.environ.get("BELFORT_EXPORTS_DIR", PROJECT_ROOT / "exports"))

DB_PATH = DATA_DIR / "belfort.db"
LOG_PATH = LOGS_DIR / "belfort.log"

APP_NAME = "Belfort Lead Parser"
APP_VERSION = "0.1.0"  # Этап 1: каркас


@dataclass
class SearchDefaults:
    """Значения по умолчанию для формы поиска."""

    target_leads: int = 50
    min_rating: float = 4.0
    sources: list[str] = field(default_factory=lambda: ["csv_import"])


@dataclass
class NetworkLimits:
    """Ограничения сетевых запросов (анти-агрессия, ТЗ п.17)."""

    timeout_seconds: float = 15.0
    min_delay_seconds: float = 1.0
    max_retries: int = 2


@dataclass
class Settings:
    search: SearchDefaults = field(default_factory=SearchDefaults)
    network: NetworkLimits = field(default_factory=NetworkLimits)


def get_settings() -> Settings:
    """Возвращает настройки приложения (пока значения по умолчанию)."""
    return Settings()


def ensure_dirs() -> None:
    """Создаёт рабочие каталоги, если их нет."""
    for directory in (DATA_DIR, LOGS_DIR, EXPORTS_DIR):
        directory.mkdir(parents=True, exist_ok=True)

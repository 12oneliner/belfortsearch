"""Интерфейс адаптера источника данных. Единый формат результата (ТЗ п.5, п.15)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class SourceStatus:
    """Сводка работы одного источника за один запуск."""

    source_name: str
    available: bool = True
    found: int = 0
    processed: int = 0
    errors: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    started_at: datetime | None = None
    finished_at: datetime | None = None

    @property
    def duration_seconds(self) -> float | None:
        if self.started_at and self.finished_at:
            return (self.finished_at - self.started_at).total_seconds()
        return None


@dataclass
class RawCompany:
    """Сырой результат любого источника — единый формат."""

    source_name: str
    external_id: str | None = None
    name: str | None = None
    city: str | None = None
    niche: str | None = None
    address: str | None = None
    phone: str | None = None
    website_url: str | None = None
    rating: float | None = None
    reviews_count: int | None = None
    card_url: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


class BaseSource(ABC):
    """Базовый класс адаптера источника."""

    name: str = "unknown"

    @abstractmethod
    def is_available(self) -> bool:
        """Доступен ли источник (API-ключ, сеть и т.п.)."""

    @abstractmethod
    def search(self, niche: str, city: str, limit: int) -> tuple[list[RawCompany], SourceStatus]:
        """Выполняет поиск и возвращает сырой результат + статус."""

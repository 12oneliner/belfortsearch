"""Дедупликация компаний (ТЗ п.12).

Точные совпадения (нормализованный телефон, карточка источника, домен) можно
объединять автоматически. Похожие названия — только на ручную проверку.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from difflib import SequenceMatcher

from database.models import Company
from utils.normalization import (
    normalize_company_name,
    normalize_phone,
    normalize_text,
    normalize_url,
)

# Порог похожести названий для сомнительного совпадения.
NAME_SIMILARITY_THRESHOLD = 0.85

MATCH_EXACT = "exact"
MATCH_DOUBTFUL = "doubtful"
MATCH_NONE = "none"


@dataclass
class MatchResult:
    """Результат сравнения двух компаний."""

    kind: str  # exact | doubtful | none
    reason: str = ""

    @property
    def is_exact(self) -> bool:
        return self.kind == MATCH_EXACT

    @property
    def is_doubtful(self) -> bool:
        return self.kind == MATCH_DOUBTFUL


def _norm_phone(company: Company) -> str:
    return company.normalized_phone or normalize_phone(company.phone)


def _norm_name(company: Company) -> str:
    return company.normalized_name or normalize_company_name(company.name)


def name_similarity(a: str | None, b: str | None) -> float:
    """Похожесть нормализованных названий, 0.0-1.0."""
    na, nb = normalize_company_name(a), normalize_company_name(b)
    if not na or not nb:
        return 0.0
    return SequenceMatcher(None, na, nb).ratio()


def compare(a: Company, b: Company) -> MatchResult:
    """Сравнивает две компании и определяет тип совпадения."""
    if a.id and b.id and a.id == b.id:
        return MatchResult(MATCH_EXACT, "одна и та же запись")

    # Точное совпадение: ссылка на карточку в источнике.
    card_a, card_b = normalize_url(a.card_url), normalize_url(b.card_url)
    if card_a and card_a == card_b:
        return MatchResult(MATCH_EXACT, "совпадает ссылка на карточку компании")

    # Точное совпадение: нормализованный телефон.
    phone_a, phone_b = _norm_phone(a), _norm_phone(b)
    if phone_a and phone_a == phone_b:
        return MatchResult(MATCH_EXACT, f"совпадает нормализованный телефон {phone_a}")

    name_a, name_b = _norm_name(a), _norm_name(b)
    same_city = normalize_text(a.city) == normalize_text(b.city)
    addr_a, addr_b = normalize_text(a.address), normalize_text(b.address)

    # Точное совпадение: название + город + адрес полностью совпадают.
    if name_a and name_a == name_b and same_city and addr_a and addr_a == addr_b:
        return MatchResult(MATCH_EXACT, "совпадают название, город и адрес")

    # Сомнительно: одинаковое название в одном городе, но адрес не совпал/неизвестен.
    if name_a and name_a == name_b and same_city:
        return MatchResult(MATCH_DOUBTFUL, "совпадает название и город, адрес не подтверждён")

    # Различающиеся числа в названиях («Фирма 1» и «Фирма 2», «СТО-5» и «СТО-7»)
    # означают разные компании: похожесть строк здесь не применяется.
    digits_a = re.findall(r"\d+", name_a)
    digits_b = re.findall(r"\d+", name_b)
    if digits_a != digits_b:
        return MatchResult(MATCH_NONE, "различаются числа в названиях")

    # Сомнительно: похожее название в одном городе.
    similarity = name_similarity(a.name, b.name)
    if same_city and similarity >= NAME_SIMILARITY_THRESHOLD:
        return MatchResult(
            MATCH_DOUBTFUL, f"похожие названия в одном городе (похожесть {similarity:.2f})"
        )

    return MatchResult(MATCH_NONE, "совпадений не найдено")


def find_matches(candidate: Company, existing: list[Company]) -> list[tuple[Company, MatchResult]]:
    """Находит все совпадения кандидата среди существующих записей.

    Точные совпадения идут первыми.
    """
    matches = []
    for other in existing:
        result = compare(candidate, other)
        if result.kind != MATCH_NONE:
            matches.append((other, result))
    matches.sort(key=lambda pair: 0 if pair[1].is_exact else 1)
    return matches


def merge_companies(primary: Company, secondary: Company) -> Company:
    """Объединяет две записи, не теряя данных.

    Заполняет пустые поля основной записи значениями из дубликата; выбирает
    большее количество отзывов и более информативный статус сайта.
    """
    merged = Company(**{**primary.__dict__})

    simple_fields = (
        "address",
        "phone",
        "card_url",
        "last_review_date",
        "social_activity",
        "score_explanation",
        "rejection_reason",
    )
    for name in simple_fields:
        if not getattr(merged, name) and getattr(secondary, name):
            setattr(merged, name, getattr(secondary, name))

    if merged.rating is None and secondary.rating is not None:
        merged.rating = secondary.rating
    if secondary.reviews_count is not None:
        if merged.reviews_count is None or secondary.reviews_count > merged.reviews_count:
            merged.reviews_count = secondary.reviews_count
    if merged.has_work_photos is None and secondary.has_work_photos is not None:
        merged.has_work_photos = secondary.has_work_photos

    # Статус сайта: подтверждённые результаты приоритетнее "не проверено".
    priority = {
        "WEBSITE_FOUND": 3,
        "NO_WEBSITE_CONFIRMED": 3,
        "UNCERTAIN": 2,
        "CHECK_FAILED": 1,
        "NOT_CHECKED": 0,
    }
    if priority.get(secondary.website_status, 0) > priority.get(merged.website_status, 0):
        merged.website_status = secondary.website_status

    # Сохраняем все источники.
    sources = [s for s in (merged.source_name, secondary.source_name) if s]
    merged.source_name = ", ".join(dict.fromkeys(", ".join(sources).split(", ")))

    # Нормализованные ключи пересчитываем.
    merged.normalized_name = normalize_company_name(merged.name)
    merged.normalized_phone = normalize_phone(merged.phone)

    # Дата первого обнаружения — самая ранняя.
    if secondary.first_seen and (not merged.first_seen or secondary.first_seen < merged.first_seen):
        merged.first_seen = secondary.first_seen

    return merged

"""Прозрачная система оценки лидов 0-100 (ТЗ п.11).

Веса (сумма ровно 100):
- подтверждённое отсутствие сайта — 30;
- признаки активности (объём отзывов) — 20;
- рейтинг и отзывы — 15;
- свежесть отзывов — 10;
- фотографии работ — 5;
- активность в соцсетях — 5;
- публичный контакт владельца/руководителя — 10;
- полнота контактных данных — 5.

Правила: баллы только за подтверждённые признаки; отсутствие данных (None)
отличается от подтверждённого отсутствия и даёт 0 баллов без штрафа;
каждое начисление фиксируется с причиной.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from database.models import (
    WEBSITE_FOUND,
    WEBSITE_NO_WEBSITE_CONFIRMED,
    Company,
    Contact,
)

# Максимальные веса по категориям.
W_NO_WEBSITE = 30
W_ACTIVITY = 20
W_RATING = 15
W_FRESHNESS = 10
W_PHOTOS = 5
W_SOCIAL = 5
W_OWNER = 10
W_CONTACTS = 5

assert W_NO_WEBSITE + W_ACTIVITY + W_RATING + W_FRESHNESS + W_PHOTOS + W_SOCIAL + W_OWNER + W_CONTACTS == 100

MIN_RATING = 4.0


@dataclass
class ScoreItem:
    """Одно начисление: категория, баллы, максимум, причина."""

    category: str
    points: int
    max_points: int
    reason: str


@dataclass
class ScoringResult:
    total: int
    items: list[ScoreItem] = field(default_factory=list)
    reject_by_rating: bool = False
    excluded_by_website: bool = False

    @property
    def explanation(self) -> str:
        lines = [f"{it.category}: {it.points}/{it.max_points} — {it.reason}" for it in self.items]
        lines.append(f"ИТОГО: {self.total}/100")
        return "\n".join(lines)


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _freshness_months(last_review: str | None, now: datetime | None = None) -> float | None:
    dt = _parse_date(last_review)
    if dt is None:
        return None
    ref = now or datetime.now(timezone.utc)
    delta_days = (ref - dt).days
    if delta_days < 0:
        return 0.0
    return delta_days / 30.44


def _owner_best_owner_score(contacts: list[Contact]) -> tuple[int, str]:
    """Возвращает (баллы, причина) за контакт владельца."""
    persons = [c for c in contacts if c.contact_type == "person" and c.value.strip()]
    if not persons:
        return 0, "контакт владельца не найден — 0 баллов"
    best = max(persons, key=lambda c: {"high": 3, "medium": 2, "low": 1}.get(c.confidence, 0))
    role = f" ({best.role})" if best.role else ""
    if best.confidence == "high":
        return W_OWNER, f"владелец{role} подтверждён ({best.source}) — {W_OWNER} баллов"
    if best.confidence == "medium":
        return 6, f"владелец{role} вероятен ({best.source}) — 6 баллов"
    return 3, f"владелец{role} с низкой достоверностью — 3 балла"


def score_company(
    company: Company,
    contacts: list[Contact] | None = None,
    now: datetime | None = None,
) -> ScoringResult:
    """Считает итоговый балл компании. Не выдумывает данные: None = 0 баллов."""
    contacts = contacts or []
    items: list[ScoreItem] = []

    # 1. Отсутствие сайта — 30.
    if company.website_status == WEBSITE_NO_WEBSITE_CONFIRMED:
        items.append(ScoreItem("Без сайта", 30, 30, "отсутствие сайта подтверждено проверками"))
    elif company.website_status == WEBSITE_FOUND:
        items.append(ScoreItem("Без сайта", 0, 30, "найден сайт компании — в лиды не входит"))
    else:
        items.append(
            ScoreItem("Без сайта", 0, 30, f"статус {company.website_status}: не подтверждено — 0 баллов")
        )

    # 2. Активность по объёму отзывов — 20.
    rc = company.reviews_count
    if rc is None:
        items.append(ScoreItem("Активность", 0, 20, "данные об отзывах отсутствуют — не проверено"))
    elif rc >= 30:
        items.append(ScoreItem("Активность", 20, 20, f"отзывов: {rc} — высокая активность"))
    elif rc >= 15:
        items.append(ScoreItem("Активность", 15, 20, f"отзывов: {rc}"))
    elif rc >= 5:
        items.append(ScoreItem("Активность", 10, 20, f"отзывов: {rc}"))
    elif rc >= 1:
        items.append(ScoreItem("Активность", 5, 20, f"отзывов: {rc} — низкая активность"))
    else:
        items.append(ScoreItem("Активность", 0, 20, "отзывов нет — 0 баллов, не признак закрытия"))

    # 3. Рейтинг — 15.
    r = company.rating
    reject_by_rating = False
    if r is None:
        items.append(ScoreItem("Рейтинг", 0, 15, "рейтинг недоступен — не проверено"))
    elif r < MIN_RATING:
        reject_by_rating = True
        items.append(ScoreItem("Рейтинг", 0, 15, f"рейтинг {r} ниже {MIN_RATING} — отклоняется"))
    elif r >= 4.8:
        items.append(ScoreItem("Рейтинг", 15, 15, f"рейтинг {r} — отличный"))
    elif r >= 4.5:
        items.append(ScoreItem("Рейтинг", 12, 15, f"рейтинг {r} — высокий"))
    elif r >= 4.2:
        items.append(ScoreItem("Рейтинг", 9, 15, f"рейтинг {r} — хороший"))
    else:
        items.append(ScoreItem("Рейтинг", 6, 15, f"рейтинг {r} — проходной"))

    # 4. Свежесть отзывов — 10.
    months = _freshness_months(company.last_review_date, now)
    if months is None:
        items.append(ScoreItem("Свежесть", 0, 10, "дата последнего отзыва неизвестна — не проверено"))
    elif months <= 6:
        items.append(ScoreItem("Свежесть", 10, 10, "последний отзыв в пределах 6 месяцев"))
    elif months <= 12:
        items.append(ScoreItem("Свежесть", 6, 10, "последний отзыв в пределах 12 месяцев"))
    else:
        items.append(ScoreItem("Свежесть", 2, 10, "последний отзыв старше года"))

    # 5. Фотографии работ — 5.
    if company.has_work_photos is True or company.has_work_photos == 1:
        items.append(ScoreItem("Фото работ", 5, 5, "есть фотографии работ"))
    elif company.has_work_photos is False or company.has_work_photos == 0:
        items.append(ScoreItem("Фото работ", 0, 5, "фотографий работ нет (подтверждено)"))
    else:
        items.append(ScoreItem("Фото работ", 0, 5, "наличие фото не проверено"))

    # 6. Активность в соцсетях — 5.
    soc = (company.social_activity or "").strip().casefold()
    if soc in ("active", "высокая", "активна", "high"):
        items.append(ScoreItem("Соцсети", 5, 5, "активность в соцсетях подтверждена"))
    elif soc in ("present", "low", "есть", "низкая", "medium"):
        items.append(ScoreItem("Соцсети", 3, 5, "соцсети есть, активность умеренная"))
    elif soc in ("none", "нет"):
        items.append(ScoreItem("Соцсети", 0, 5, "соцсетей нет (подтверждено)"))
    else:
        items.append(ScoreItem("Соцсети", 0, 5, "соцсети не проверены"))

    # 7. Контакт владельца — 10.
    owner_points, owner_reason = _owner_best_owner_score(contacts)
    items.append(ScoreItem("Владелец", owner_points, 10, owner_reason))

    # 8. Полнота контактов — 5 (телефон 3 + адрес 2).
    cp = 0
    parts = []
    if company.phone and company.phone.strip():
        cp += 3
        parts.append("телефон есть (+3)")
    else:
        parts.append("телефона нет (+0)")
    if company.address and company.address.strip():
        cp += 2
        parts.append("адрес есть (+2)")
    else:
        parts.append("адреса нет (+0)")
    items.append(ScoreItem("Контакты", cp, 5, "; ".join(parts)))

    total = sum(it.points for it in items)
    return ScoringResult(
        total=min(total, 100),
        items=items,
        reject_by_rating=reject_by_rating,
        excluded_by_website=(company.website_status == WEBSITE_FOUND),
    )

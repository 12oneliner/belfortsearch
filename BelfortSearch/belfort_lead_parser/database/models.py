"""Модели данных лида (ТЗ п.7). Dataclasses повторяют схему SQLite."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

# Статусы проверки сайта (ТЗ п.9).
WEBSITE_NO_WEBSITE_CONFIRMED = "NO_WEBSITE_CONFIRMED"
WEBSITE_FOUND = "WEBSITE_FOUND"
WEBSITE_UNCERTAIN = "UNCERTAIN"
WEBSITE_NOT_CHECKED = "NOT_CHECKED"
WEBSITE_CHECK_FAILED = "CHECK_FAILED"

WEBSITE_STATUSES = (
    WEBSITE_NO_WEBSITE_CONFIRMED,
    WEBSITE_FOUND,
    WEBSITE_UNCERTAIN,
    WEBSITE_NOT_CHECKED,
    WEBSITE_CHECK_FAILED,
)

# Статусы обработки (ТЗ п.4).
STATUS_FOUND = "found"
STATUS_CHECKING = "checking"
STATUS_FIT = "fit"
STATUS_DOUBTFUL = "doubtful"
STATUS_DUPLICATE = "duplicate"
STATUS_REJECTED = "rejected"
STATUS_SOURCE_ERROR = "source_error"

PROCESSING_STATUSES = (
    STATUS_FOUND,
    STATUS_CHECKING,
    STATUS_FIT,
    STATUS_DOUBTFUL,
    STATUS_DUPLICATE,
    STATUS_REJECTED,
    STATUS_SOURCE_ERROR,
)


@dataclass
class Company:
    """Компания-лид. None = неизвестно / не проверено (не выдумываем данные)."""

    id: str
    name: str
    niche: str = ""
    city: str = ""
    address: str | None = None
    phone: str | None = None
    normalized_phone: str = ""
    normalized_name: str = ""
    card_url: str | None = None
    website_url: str | None = None
    source_name: str = ""
    rating: float | None = None
    reviews_count: int | None = None
    website_status: str = WEBSITE_NOT_CHECKED
    score: int = 0
    score_explanation: str | None = None
    rejection_reason: str | None = None
    processing_status: str = STATUS_FOUND
    first_seen: str = ""
    last_checked: str = ""
    last_review_date: str | None = None
    has_work_photos: int | None = None
    social_activity: str | None = None


@dataclass
class Contact:
    id: str
    company_id: str
    contact_type: str = ""  # phone | telegram | email | person ...
    value: str = ""
    role: str | None = None
    source: str = ""
    proof_url: str | None = None
    confidence: str = "low"  # low | medium | high


@dataclass
class WebsiteCheck:
    id: str
    company_id: str
    status: str = WEBSITE_NOT_CHECKED
    evidence: str | None = None
    checked_at: str = ""


@dataclass
class Run:
    id: str
    started_at: str = ""
    finished_at: str | None = None
    niche: str = ""
    city: str = ""
    sources: str = ""  # JSON-список
    target_leads: int = 50
    found: int = 0
    unique_count: int = 0
    checked_websites: int = 0
    confirmed_no_website: int = 0
    quality_leads: int = 0
    rejected: int = 0
    doubtful: int = 0
    errors: str | None = None

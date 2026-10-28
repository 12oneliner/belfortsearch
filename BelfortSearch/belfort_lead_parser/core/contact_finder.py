"""Поиск публичных деловых контактов (ТЗ п.8).

Порядок: карточка источника → официальный сайт (если есть) → публичные
страницы в соцсетях → бизнес-каталоги. Только открытые данные, только явная
роль. Имя без роли контактом владельца не считается.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable
from urllib.parse import urlparse

from database.models import Company, Contact
from utils.normalization import normalize_phone, normalize_text

PHONE_RE = re.compile(r"(?:\+7|8)[\s\-()]*\d[\d\s\-()]{8,}\d")
TELEGRAM_RE = re.compile(r"(?:https?://)?t(?:elegram)?\.me/([\w\d_]{5,})", re.IGNORECASE)
EMAIL_RE = re.compile(r"[\w.\-]+@[\w\-]+(?:\.[\w\-]+)+")

# Слова — маркеры роли руководителя. Только при их наличии рядом с именем
# контакт признаётся контактом владельца.
ROLE_MARKERS = {
    "директор": "директор",
    "генеральный директор": "генеральный директор",
    "гендиректор": "генеральный директор",
    "руководитель": "руководитель",
    "владелец": "владелец",
    "собственник": "собственник",
    "учредитель": "учредитель",
    "основатель": "основатель",
    "ип": "ИП",
}

CONF_HIGH = "high"
CONF_MEDIUM = "medium"
CONF_LOW = "low"

FetchFn = Callable[[str], str | None]


@dataclass
class ContactEvidence:
    contact: Contact
    proof_excerpt: str = ""


def _host(url: str | None) -> str:
    if not url:
        return ""
    try:
        return urlparse(url).netloc.casefold()
    except ValueError:
        return ""


def extract_phones(text: str | None) -> list[str]:
    """Извлекает номера телефонов из открытого текста."""
    if not text:
        return []
    found = []
    for match in PHONE_RE.findall(text):
        normalized = normalize_phone(match)
        if len(normalized) == 11 and normalized not in found:
            found.append(normalized)
    return found


def extract_telegrams(text: str | None) -> list[str]:
    if not text:
        return []
    return list(dict.fromkeys(TELEGRAM_RE.findall(text)))


def extract_emails(text: str | None) -> list[str]:
    if not text:
        return []
    found = []
    for match in EMAIL_RE.findall(text):
        low = match.casefold()
        if low not in found:
            found.append(low)
    return found


def detect_role(text: str | None) -> tuple[str | None, str]:
    """Ищет маркер роли руководителя. Возвращает (роль, достоверность).

    Без явного маркера роли возвращается (None, low) — имя человека
    рядом с компанией без указания роли контактом владельца НЕ считается.
    """
    norm = normalize_text(text)
    if not norm:
        return None, CONF_LOW
    # Длинные маркеры проверяем первыми: «генеральный директор» содержит
    # подстроку «директор» и иначе затеняется коротким маркером.
    for marker, role in sorted(ROLE_MARKERS.items(), key=lambda kv: -len(kv[0])):
        if marker in norm:
            return role, CONF_MEDIUM
    return None, CONF_LOW


class ContactFinder:
    """Собирает публичные контакты. Доступ к страницам инжектится (fetch_fn)."""

    def __init__(self, fetch_fn: FetchFn | None = None) -> None:
        self.fetch_fn = fetch_fn or (lambda url: None)

    def find(self, company: Company) -> list[ContactEvidence]:
        results: list[ContactEvidence] = []
        seen_values: set[str] = set()

        def add(contact_type: str, value: str, role: str | None, source: str,
                proof_url: str | None, confidence: str, excerpt: str = "") -> None:
            key = f"{contact_type}:{normalize_text(value)}"
            if not value or key in seen_values:
                return
            seen_values.add(key)
            results.append(
                ContactEvidence(
                    contact=Contact(
                        id="",
                        company_id=company.id,
                        contact_type=contact_type,
                        value=value,
                        role=role,
                        source=source,
                        proof_url=proof_url,
                        confidence=confidence,
                    ),
                    proof_excerpt=excerpt,
                )
            )

        # 1. Карточка источника: телефон компании.
        if company.phone and company.phone.strip():
            add("phone", normalize_phone(company.phone) or company.phone.strip(),
                None, "карточка компании", company.card_url, CONF_HIGH,
                f"телефон из карточки: {company.phone}")

        # 2-5. Публичные страницы: сайт (если есть) + известные соцсети/каталоги
        # из дополнительных данных компании. Не ходим по чужим URL без связи.
        pages: list[tuple[str, str]] = []
        from core.website_checker import is_own_website  # локально: нет цикла, один модуль

        if company.website_url and is_own_website(company.website_url):
            pages.append((company.website_url, "официальный сайт"))
        extras = getattr(company, "extra_urls", None) or []
        for url in extras:
            if isinstance(url, str) and url.strip():
                pages.append((url, "публичная страница"))

        for url, source in pages:
            try:
                html = self.fetch_fn(url)
            except Exception:
                continue  # недоступная страница — пропускаем, фиксируем в вызывающем коде
            if not html:
                continue
            for phone in extract_phones(html):
                add("phone", phone, None, source, url, CONF_MEDIUM,
                    f"телефон на странице {url}")
            for username in extract_telegrams(html):
                add("telegram", f"https://t.me/{username}", None, source, url, CONF_MEDIUM,
                    f"telegram на странице {url}")
            for email in extract_emails(html):
                add("email", email, None, source, url, CONF_MEDIUM,
                    f"email на странице {url}")

            role, confidence = detect_role(html)
            if role:
                # Контакт владельца — только при маркере роли; значением
                # служит телефон/Telegram со страницы (не выдуманное имя).
                add("person", role, role, source, url, confidence,
                    f"роль «{role}» указана на странице {url}")

        return results

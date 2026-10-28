"""Нормализация строк, телефонов и названий компаний."""

from __future__ import annotations

import re
import unicodedata

# Маппинг популярных русских сокращений/форм организаций к канонической форме.
_LEGAL_SUFFIXES = {
    "ооо": "ооо",
    "ип": "ип",
    "ао": "ао",
    "пао": "пао",
    "зао": "зао",
    "оао": "оао",
}

_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)
_WS_RE = re.compile(r"\s+")


def normalize_text(value: str | None) -> str:
    """Приводит строку к нижнему регистру, удаляет пунктуацию и лишние пробелы."""
    if not value:
        return ""
    text = unicodedata.normalize("NFKC", value).casefold()
    text = _PUNCT_RE.sub(" ", text)
    text = _WS_RE.sub(" ", text).strip()
    return text


def normalize_company_name(name: str | None) -> str:
    """Нормализует название компании для дедупликации."""
    return normalize_text(name)


def normalize_phone(phone: str | None) -> str:
    """Нормализует номер телефона до цифр (с учётом кода страны)."""
    if not phone:
        return ""
    digits = re.sub(r"\D", "", phone)
    if len(digits) == 11 and digits.startswith("8"):
        digits = "7" + digits[1:]
    return digits


def normalize_url(url: str | None) -> str:
    """Приводит URL к нижнему регистру и убирает конечный слеш/протокол-дубль."""
    if not url:
        return ""
    text = url.strip().casefold()
    if text.endswith("/"):
        text = text[:-1]
    return text

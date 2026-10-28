"""Экспорт в CSV с корректной кодировкой UTF-8 (ТЗ п.14)."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable

CSV_COLUMNS = [
    ("id", "ID"),
    ("name", "Название компании"),
    ("niche", "Ниша"),
    ("city", "Город"),
    ("address", "Адрес"),
    ("phone", "Телефон"),
    ("card_url", "Ссылка на карточку"),
    ("source_name", "Источник"),
    ("rating", "Рейтинг"),
    ("reviews_count", "Отзывы"),
    ("website_status", "Статус сайта"),
    ("score", "Балл"),
    ("score_explanation", "Расшифровка балла"),
    ("processing_status", "Статус обработки"),
    ("first_seen", "Дата первого обнаружения"),
    ("last_checked", "Дата последней проверки"),
]


def export_csv(rows: Iterable, path: str | Path, delimiter: str = ";") -> Path:
    """Экспортирует список объектов/словарей в CSV (UTF-8 с BOM для Excel).

    delimiter ';' — удобен для русского Excel по умолчанию.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle, delimiter=delimiter, quoting=csv.QUOTE_MINIMAL)
        writer.writerow([title for _, title in CSV_COLUMNS])
        for row in rows:
            values = []
            for field_name, _ in CSV_COLUMNS:
                value = _get(row, field_name)
                values.append("" if value is None else value)
            writer.writerow(values)

    return path


def _get(row, field_name: str):
    if isinstance(row, dict):
        return row.get(field_name)
    return getattr(row, field_name, None)

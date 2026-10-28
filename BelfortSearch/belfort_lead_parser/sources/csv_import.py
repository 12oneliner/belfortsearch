"""Импорт компаний из CSV-файла пользователя (ТЗ п.5, режим без API).

Это полностью рабочий источник без ключей и без обхода ограничений:
пользователь сам выгружает список компаний (например, разрешённым экспортом
или вручную) и загружает файл в приложение.
"""

from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path

from sources.base import BaseSource, RawCompany, SourceStatus
from utils.normalization import normalize_text

SOURCE_NAME = "csv_import"

# Допустимые названия колонок (регистр и пробелы не важны).
COLUMN_ALIASES = {
    "name": {"название", "наименование", "компания", "name", "company"},
    "city": {"город", "city"},
    "address": {"адрес", "address"},
    "phone": {"телефон", "тел", "phone"},
    "website_url": {"сайт", "website", "site", "url сайта"},
    "card_url": {"ссылка", "карточка", "card_url", "ссылка на карточку"},
    "rating": {"рейтинг", "rating"},
    "reviews_count": {"отзывы", "количество отзывов", "reviews", "reviews_count"},
    "niche": {"ниша", "niche", "категория"},
}


def _map_headers(fieldnames: list[str] | None) -> dict[str, str]:
    """Сопоставляет колонки файла полям RawCompany.

    Сначала ищется точное совпадение с алиасом, затем — вхождение алиаса
    в заголовок («Название компании» → name). Более длинные алиасы
    проверяются первыми, чтобы «количество отзывов» не свелось к «отзывы».
    """
    mapping: dict[str, str] = {}
    normalized_aliases: list[tuple[str, str]] = []
    for field_name, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            normalized_aliases.append((normalize_text(alias), field_name))
    normalized_aliases.sort(key=lambda pair: -len(pair[0]))

    for raw in fieldnames or []:
        key = normalize_text(raw)
        if not key:
            continue
        exact = next((f for alias, f in normalized_aliases if alias == key), None)
        if exact is not None:
            mapping[raw] = exact
            continue
        partial = next(
            (f for alias, f in normalized_aliases if alias and alias in key.split()
             or alias and alias in key),
            None,
        )
        if partial is not None:
            mapping[raw] = partial
    return mapping


def _to_float(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return float(str(value).replace(",", "."))
    except ValueError:
        return None


def _to_int(value: str | None) -> int | None:
    if not value:
        return None
    try:
        return int(float(str(value).replace(",", ".")))
    except ValueError:
        return None


class CsvImportSource(BaseSource):
    """Читает компании из CSV-файла, указанного пользователем."""

    name = SOURCE_NAME

    def __init__(self, file_path: str | Path | None = None) -> None:
        self.file_path = Path(file_path) if file_path else None

    def is_available(self) -> bool:
        return self.file_path is not None and self.file_path.exists()

    def search(self, niche: str, city: str, limit: int) -> tuple[list[RawCompany], SourceStatus]:
        """Загружает строки файла, фильтруя по нише и городу, если они заданы."""
        status = SourceStatus(
            source_name=self.name,
            started_at=datetime.now(timezone.utc),
        )

        if self.file_path is None:
            status.available = False
            status.errors.append("Файл CSV не выбран")
            status.finished_at = datetime.now(timezone.utc)
            return [], status

        if not self.file_path.exists():
            status.available = False
            status.errors.append(f"Файл не найден: {self.file_path}")
            status.finished_at = datetime.now(timezone.utc)
            return [], status

        results: list[RawCompany] = []
        city_norm = normalize_text(city)
        niche_norm = normalize_text(niche)

        try:
            # utf-8-sig: корректно читает файлы, сохранённые Excel с BOM.
            with self.file_path.open("r", encoding="utf-8-sig", newline="") as handle:
                first_line = handle.readline()
                handle.seek(0)
                # Определяем разделитель вручную: csv.Sniffer на части файлов
                # поднимает «Could not determine delimiter», и тогда файл
                # ошибочно считался бы недоступным.
                if ";" in first_line:
                    delimiter = ";"
                elif "\t" in first_line:
                    delimiter = "\t"
                else:
                    delimiter = ","
                reader = csv.DictReader(handle, delimiter=delimiter)
                mapping = _map_headers(reader.fieldnames)
                if "name" not in mapping.values():
                    status.available = False
                    status.errors.append(
                        "В файле нет колонки с названием компании "
                        "(ожидается «Название», «Наименование», «Компания» или name)"
                    )
                    status.finished_at = datetime.now(timezone.utc)
                    return [], status

                for row in reader:
                    status.found += 1
                    data: dict[str, str] = {}
                    for raw_column, field_name in mapping.items():
                        value = (row.get(raw_column) or "").strip()
                        if value:
                            data[field_name] = value

                    name = data.get("name")
                    if not name:
                        continue

                    row_city = data.get("city", city)
                    row_niche = data.get("niche", niche)

                    # Не смешиваем города и ниши: фильтруем, если заданы.
                    # Совпадение — нестрогое: «Ростов» найдёт «Ростов-на-Дону»,
                    # «потолки» найдёт «натяжные потолки» и наоборот.
                    if city_norm and city_norm not in normalize_text(row_city) and normalize_text(row_city) not in city_norm:
                        continue
                    if niche_norm and data.get("niche") and niche_norm not in normalize_text(row_niche) and normalize_text(row_niche) not in niche_norm:
                        continue

                    results.append(
                        RawCompany(
                            source_name=self.name,
                            name=name,
                            city=row_city,
                            niche=row_niche,
                            address=data.get("address"),
                            phone=data.get("phone"),
                            website_url=data.get("website_url"),
                            card_url=data.get("card_url"),
                            rating=_to_float(data.get("rating")),
                            reviews_count=_to_int(data.get("reviews_count")),
                        )
                    )
                    status.processed += 1
                    if limit and len(results) >= limit:
                        break

        except OSError as exc:
            status.available = False
            status.errors.append(f"Ошибка чтения файла: {exc}")

        status.limitations.append(
            "Полнота данных зависит от файла пользователя: приложение не дополняет "
            "строки сведениями из сторонних источников."
        )
        status.finished_at = datetime.now(timezone.utc)
        return results, status

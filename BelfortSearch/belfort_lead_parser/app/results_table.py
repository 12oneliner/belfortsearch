"""Модель таблицы результатов с сортировкой и фильтрацией (ТЗ п.4)."""

from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt

from database.models import Company

# Отображаемые колонки: (поле, заголовок на русском, ширина).
COLUMNS: list[tuple[str, str, int]] = [
    ("name", "Название", 240),
    ("city", "Город", 130),
    ("niche", "Ниша", 150),
    ("phone", "Телефон", 130),
    ("address", "Адрес", 220),
    ("rating", "Рейтинг", 80),
    ("reviews_count", "Отзывы", 80),
    ("website_status", "Статус сайта", 170),
    ("score", "Балл", 70),
    ("processing_status", "Статус", 120),
]

# Понятные пользователю названия статусов (ТЗ п.4).
STATUS_LABELS = {
    "found": "найдено",
    "checking": "проверяется",
    "fit": "подходит",
    "doubtful": "сомнительный результат",
    "duplicate": "дубликат",
    "rejected": "отклонён",
    "source_error": "ошибка источника",
}

WEBSITE_STATUS_LABELS = {
    "NO_WEBSITE_CONFIRMED": "сайта нет (подтверждено)",
    "WEBSITE_FOUND": "сайт найден",
    "UNCERTAIN": "неопределённо",
    "NOT_CHECKED": "не проверено",
    "CHECK_FAILED": "проверка не удалась",
}


class ResultsTableModel(QAbstractTableModel):
    """Таблица компаний для QTableView."""

    def __init__(self, companies: list[Company] | None = None) -> None:
        super().__init__()
        self._companies: list[Company] = list(companies or [])

    # --- обязательные методы Qt ---

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._companies)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(COLUMNS)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        company = self._companies[index.row()]
        field_name, _title, _width = COLUMNS[index.column()]
        value = getattr(company, field_name, None)

        if role == Qt.ItemDataRole.DisplayRole:
            if value is None or value == "":
                return "—"  # нет данных: не выдумываем значение
            if field_name == "processing_status":
                return STATUS_LABELS.get(str(value), str(value))
            if field_name == "website_status":
                return WEBSITE_STATUS_LABELS.get(str(value), str(value))
            return str(value)

        if role == Qt.ItemDataRole.ToolTipRole and field_name == "score":
            return company.score_explanation or "Расшифровка недоступна"

        if role == Qt.ItemDataRole.TextAlignmentRole:
            if field_name in ("rating", "reviews_count", "score"):
                return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        return None

    def headerData(self, section: int, orientation: Qt.Orientation,
                   role: int = Qt.ItemDataRole.DisplayRole):
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            return COLUMNS[section][1]
        return section + 1

    # --- работа с данными ---

    def set_companies(self, companies: list[Company]) -> None:
        self.beginResetModel()
        self._companies = list(companies)
        self.endResetModel()

    def company_at(self, row: int) -> Company | None:
        if 0 <= row < len(self._companies):
            return self._companies[row]
        return None

    def companies(self) -> list[Company]:
        return list(self._companies)

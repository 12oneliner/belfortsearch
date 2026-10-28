"""Диалоги: история запусков, настройки источников и просмотр лида."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
)

from config.settings import get_settings
from core.deduplication import NAME_SIMILARITY_THRESHOLD
from database.repository import CompanyRepository, RunRepository


class RunHistoryDialog(QDialog):
    """Просмотр истории запусков."""

    def __init__(self, runs: RunRepository, parent=None) -> None:
        super().__init__(parent)
        self.runs = runs
        self.setWindowTitle("История запусков")
        self.resize(900, 480)

        layout = QVBoxLayout(self)
        self.table = QTableWidget()
        layout.addWidget(self.table)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._load_runs()

    def _load_runs(self) -> None:
        rows = self.runs.list_recent(limit=100)
        headers = [
            "Дата", "Ниша", "Город", "Источники", "Цель",
            "Найдено", "Уникальных", "Без сайта", "Качественных", "Отклонено", "Сомнительных",
        ]
        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        self.table.setRowCount(len(rows))
        for i, run in enumerate(rows):
            values = [
                run.started_at[:19].replace("T", " "),
                run.niche, run.city, run.sources, str(run.target_leads),
                str(run.found), str(run.unique_count), str(run.confirmed_no_website),
                str(run.quality_leads), str(run.rejected), str(run.doubtful),
            ]
            for j, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(i, j, item)
        self.table.resizeColumnsToContents()


class SourcesDialog(QDialog):
    """Настройки источников и диагностика.

    Честно показывает доступность: картографические адаптеры помечены
    ограничениями до появления разрешённого способа доступа.
    """

    AVAILABLE_SOURCES: list[tuple[str, str, str]] = [
        ("csv_import", "Импорт CSV", "Работает: файл выбирает пользователь"),
        ("google_maps", "Google Maps", "Ограничение: без API автоматизация недоступна"),
        ("yandex", "Яндекс Карты", "Ограничение: без API автоматизация недоступна"),
        ("two_gis", "2ГИС", "Ограничение: без API автоматизация недоступна"),
        ("web_search", "Веб-поиск", "Планируется: только разрешённые запросы"),
    ]

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Источники данных и диагностика")
        self.resize(560, 320)

        layout = QVBoxLayout(self)
        info = QLabel(
            "Рабочий источник сейчас один — импорт CSV. "
            "Картографические сервисы будут добавлены, когда появится "
            "разрешённый способ получения данных без платных ключей. "
            "Платные подписки не обязательны."
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        self.table = QTableWidget()
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["Код", "Название", "Статус"])
        self.table.setRowCount(len(self.AVAILABLE_SOURCES))
        for i, (code, title, status) in enumerate(self.AVAILABLE_SOURCES):
            for j, value in enumerate((code, title, status)):
                item = QTableWidgetItem(value)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(i, j, item)
        self.table.resizeColumnsToContents()
        layout.addWidget(self.table)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def selected_working_sources(self) -> list[str]:
        return ["csv_import"]


class LeadDetailsDialog(QDialog):
    """Карточка лида: данные, расшифровка балла, контакты, история."""

    def __init__(self, company_id: str, companies: CompanyRepository, parent=None) -> None:
        super().__init__(parent)
        self.companies = companies
        self.company_id = company_id
        self.setWindowTitle("Карточка лида")
        self.resize(640, 520)

        layout = QVBoxLayout(self)
        self.text = QTextEdit()
        self.text.setReadOnly(True)
        layout.addWidget(self.text)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._load()

    def _load(self) -> None:
        company = self.companies.get(self.company_id)
        if company is None:
            self.text.setPlainText("Компания не найдена (возможно, удалена).")
            return
        lines = [
            f"Название: {company.name or '—'}",
            f"Ниша: {company.niche or '—'}; город: {company.city or '—'}",
            f"Адрес: {company.address or '—'}",
            f"Телефон: {company.phone or '—'}",
            f"Карточка: {company.card_url or '—'}",
            f"Рейтинг: {company.rating if company.rating is not None else '—'}; "
            f"отзывов: {company.reviews_count if company.reviews_count is not None else '—'}",
            f"Статус сайта: {company.website_status}",
            f"Итоговый балл: {company.score}",
            "",
            "Расшифровка балла:",
            company.score_explanation or "—",
            "",
            "Причина отклонения:",
            company.rejection_reason or "—",
        ]
        self.text.setPlainText("\n".join(lines))

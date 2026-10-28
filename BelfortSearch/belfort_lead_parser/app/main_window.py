"""Главное окно Belfort Lead Parser (ТЗ п.4)."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from app.dialogs import LeadDetailsDialog, RunHistoryDialog, SourcesDialog
from app.results_table import COLUMNS, ResultsTableModel
from app.workers import SearchWorker, start_worker
from config import settings
from database.connection import init_db
from database.repository import CompanyRepository, RunRepository
from exporters.csv_exporter import export_csv
from exporters.excel_exporter import export_excel
from sources.csv_import import CsvImportSource
from sources.web_search_source import WebSearchSource


class MainWindow(QMainWindow):
    """Главное окно: форма поиска, прогресс, таблица, экспорт, история."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"{settings.APP_NAME} {settings.APP_VERSION}")
        self.resize(1280, 760)

        self.conn = init_db()
        self.companies = CompanyRepository(self.conn)
        self.runs = RunRepository(self.conn)

        self.worker: SearchWorker | None = None
        self.thread: QThread | None = None
        self.csv_path: Path | None = None
        self.last_stats: dict | None = None

        self._build_ui()
        self._reload_table()

    # ------------------------------ интерфейс ------------------------------

    def _build_ui(self) -> None:
        central = QWidget()
        root = QVBoxLayout(central)

        root.addWidget(self._build_search_box())
        root.addWidget(self._build_progress_box())
        root.addWidget(self._build_table_box(), stretch=1)
        root.addLayout(self._build_bottom_buttons())

        self.setCentralWidget(central)

    def _build_search_box(self) -> QGroupBox:
        box = QGroupBox("Параметры поиска")
        layout = QVBoxLayout(box)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Ниша:"))
        self.niche_input = QLineEdit()
        self.niche_input.setPlaceholderText("например, натяжные потолки")
        row1.addWidget(self.niche_input, stretch=2)

        row1.addWidget(QLabel("Город:"))
        self.city_input = QLineEdit()
        self.city_input.setPlaceholderText("например, Ростов-на-Дону")
        row1.addWidget(self.city_input, stretch=2)

        row1.addWidget(QLabel("Цель (лидов):"))
        self.target_input = QSpinBox()
        self.target_input.setRange(1, 1000)
        self.target_input.setValue(settings.get_settings().search.target_leads)
        row1.addWidget(self.target_input)
        layout.addLayout(row1)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Минимальный рейтинг:"))
        self.min_rating_input = QDoubleSpinBox()
        self.min_rating_input.setRange(0.0, 5.0)
        self.min_rating_input.setSingleStep(0.1)
        self.min_rating_input.setValue(settings.get_settings().search.min_rating)
        row2.addWidget(self.min_rating_input)

        self.keep_low_rating = QCheckBox("Оставлять компании с низким рейтингом отдельно")
        row2.addWidget(self.keep_low_rating)

        self.use_web_search = QCheckBox("Веб-поиск (без ключей)")
        self.use_web_search.setChecked(True)
        self.use_web_search.setToolTip(
            "Ищет компании в обычной поисковой выдаче по нише и городу.\n"
            "Телефоны, адреса и рейтинги выдача не отдаёт — эти поля останутся пустыми."
        )
        row2.addWidget(self.use_web_search)
        row2.addStretch(1)

        self.csv_button = QPushButton("Выбрать CSV-файл источника…")
        self.csv_button.clicked.connect(self._choose_csv)
        row2.addWidget(self.csv_button)

        self.csv_label = QLabel("файл не выбран")
        row2.addWidget(self.csv_label)
        layout.addLayout(row2)

        row3 = QHBoxLayout()
        self.start_button = QPushButton("Начать поиск")
        self.start_button.clicked.connect(self._start_search)
        row3.addWidget(self.start_button)

        self.stop_button = QPushButton("Остановить поиск")
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self._stop_search)
        row3.addWidget(self.stop_button)

        self.sources_button = QPushButton("Источники и диагностика")
        self.sources_button.clicked.connect(self._open_sources)
        row3.addWidget(self.sources_button)

        self.history_button = QPushButton("История запусков")
        self.history_button.clicked.connect(self._open_history)
        row3.addWidget(self.history_button)
        row3.addStretch(1)
        layout.addLayout(row3)

        return box

    def _build_progress_box(self) -> QGroupBox:
        box = QGroupBox("Ход поиска")
        layout = QVBoxLayout(box)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        layout.addWidget(self.progress)

        self.counters_label = QLabel(
            "Найдено: 0 | Проверено сайтов: 0 | Подходит: 0 | "
            "Сомнительных: 0 | Отклонено: 0"
        )
        layout.addWidget(self.counters_label)

        self.status_label = QLabel("Готов к работе.")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        return box

    def _build_table_box(self) -> QGroupBox:
        box = QGroupBox("Результаты")
        layout = QVBoxLayout(box)

        filters = QHBoxLayout()
        filters.addWidget(QLabel("Показывать:"))
        self.filter_combo = QComboBox()
        self.filter_combo.addItem("Все компании", None)
        self.filter_combo.addItem("Только качественные лиды", "fit")
        self.filter_combo.addItem("Сомнительные результаты", "doubtful")
        self.filter_combo.addItem("Отклонённые", "rejected")
        self.filter_combo.addItem("Дубликаты", "duplicate")
        self.filter_combo.currentIndexChanged.connect(self._reload_table)
        filters.addWidget(self.filter_combo)

        filters.addWidget(QLabel("Минимальный балл:"))
        self.min_score_input = QSpinBox()
        self.min_score_input.setRange(0, 100)
        self.min_score_input.valueChanged.connect(self._reload_table)
        filters.addWidget(self.min_score_input)
        filters.addStretch(1)

        self.details_button = QPushButton("Открыть карточку лида")
        self.details_button.clicked.connect(self._open_details)
        filters.addWidget(self.details_button)

        self.delete_button = QPushButton("Удалить выбранную компанию")
        self.delete_button.clicked.connect(self._delete_selected)
        filters.addWidget(self.delete_button)
        layout.addLayout(filters)

        self.table_model = ResultsTableModel()
        self.table = QTableView()
        self.table.setModel(self.table_model)
        self.table.setSortingEnabled(False)
        self.table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Interactive
        )
        layout.addWidget(self.table)

        return box

    def _build_bottom_buttons(self) -> QHBoxLayout:
        row = QHBoxLayout()
        self.export_excel_button = QPushButton("Экспорт в Excel")
        self.export_excel_button.clicked.connect(self._export_excel)
        row.addWidget(self.export_excel_button)

        self.export_csv_button = QPushButton("Экспорт в CSV")
        self.export_csv_button.clicked.connect(self._export_csv)
        row.addWidget(self.export_csv_button)
        row.addStretch(1)

        self.rows_label = QLabel("Строк в таблице: 0")
        row.addWidget(self.rows_label)
        return row

    # ------------------------------ действия ------------------------------

    def _choose_csv(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Выберите CSV-файл со списком компаний", "",
            "CSV-файлы (*.csv);;Все файлы (*.*)",
        )
        if path:
            self.csv_path = Path(path)
            self.csv_label.setText(self.csv_path.name)

    def _selected_sources(self) -> list:
        """Собирает активные источники. Сейчас рабочий — импорт CSV."""
        sources = []
        if self.csv_path is not None:
            sources.append(CsvImportSource(self.csv_path))
        # Веб-поиск не нуждается ни в ключе, ни в файле — только в сети.
        if self.use_web_search.isChecked():
            sources.append(WebSearchSource())
        return sources

    def _start_search(self) -> None:
        niche = self.niche_input.text().strip()
        city = self.city_input.text().strip()

        if not niche or not city:
            QMessageBox.warning(self, "Не заполнены поля",
                                "Укажите нишу и город: они задаются вручную при каждом запуске.")
            return

        sources = self._selected_sources()
        if not sources:
            QMessageBox.warning(
                self, "Нет доступных источников",
                "Ни один источник не доступен.\n\n"
                "Картографические сервисы пока не автоматизируются без API: "
                "это ограничение показано в разделе «Источники и диагностика».",
            )
            return

        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.progress.setRange(0, 0)  # неопределённый прогресс
        self.status_label.setText("Поиск запущен…")

        self.worker = SearchWorker(
            niche=niche, city=city, sources=sources,
            target_leads=self.target_input.value(),
        )
        self.worker.message.connect(self.status_label.setText)
        self.worker.progress.connect(self._update_counters)
        self.worker.finished.connect(self._on_finished)
        self.worker.failed.connect(self._on_failed)
        self.thread = start_worker(self.worker)

    def _stop_search(self) -> None:
        if self.worker is not None:
            self.worker.request_stop()
            self.stop_button.setEnabled(False)

    def _update_counters(self, counters: dict) -> None:
        self.counters_label.setText(
            "Найдено: {found} | Проверено сайтов: {checked_websites} | "
            "Подходит: {quality_leads} | Сомнительных: {doubtful} | "
            "Отклонено: {rejected}".format(**counters)
        )

    def _on_finished(self, stats: dict) -> None:
        self.last_stats = stats
        self.progress.setRange(0, 100)
        self.progress.setValue(100)
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self._update_counters(stats)
        self._reload_table()

        duration = stats.get("duration_seconds")
        duration_text = f"{duration:.1f} с" if duration else "—"
        self.status_label.setText(
            f"Запуск завершён за {duration_text}. "
            f"Найдено: {stats.get('found', 0)}, "
            f"уникальных: {stats.get('unique', 0)}, "
            f"качественных лидов: {stats.get('quality_leads', 0)}, "
            f"сомнительных: {stats.get('doubtful', 0)}, "
            f"отклонено: {stats.get('rejected', 0)}."
        )

        errors = self.runs.list_errors(stats["run_id"])
        if errors:
            messages = "\n".join(f"• {row['source_name']}: {row['message']}" for row in errors)
            QMessageBox.information(
                self, "Ограничения и ошибки источников",
                f"Запуск завершён, но часть источников сообщила об ограничениях:\n\n{messages}",
            )

    def _on_failed(self, message: str) -> None:
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.status_label.setText(f"Поиск не завершён: {message}")
        QMessageBox.critical(self, "Ошибка поиска", message)

    def _reload_table(self) -> None:
        status = self.filter_combo.currentData() if hasattr(self, "filter_combo") else None
        min_score = self.min_score_input.value() if hasattr(self, "min_score_input") else 0
        companies = self.companies.list_all(
            processing_status=status,
            min_score=min_score or None,
        )
        self.table_model.set_companies(companies)
        for index, (_field, _title, width) in enumerate(COLUMNS):
            self.table.setColumnWidth(index, width)
        self.rows_label.setText(f"Строк в таблице: {len(companies)}")

    def _selected_company(self):
        rows = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        if not rows:
            return None
        return self.table_model.company_at(rows[0].row())

    def _open_details(self) -> None:
        company = self._selected_company()
        if company is None:
            QMessageBox.information(self, "Не выбрана строка",
                                    "Выберите компанию в таблице.")
            return
        LeadDetailsDialog(company.id, self.companies, self).exec()

    def _delete_selected(self) -> None:
        company = self._selected_company()
        if company is None:
            QMessageBox.information(self, "Не выбрана строка",
                                    "Выберите компанию в таблице.")
            return
        answer = QMessageBox.question(
            self, "Удалить компанию?",
            f"Удалить «{company.name}» и все связанные контакты и проверки "
            "из локальной базы? Действие необратимо.",
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.companies.delete(company.id)
            self._reload_table()

    def _open_history(self) -> None:
        RunHistoryDialog(self.runs, self).exec()

    def _open_sources(self) -> None:
        SourcesDialog(self).exec()

    def _rows_for_export(self) -> list:
        selected = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        if len(selected) > 1:
            return [self.table_model.company_at(index.row()) for index in selected]
        return self.table_model.companies()

    def _export_excel(self) -> None:
        rows = self._rows_for_export()
        if not rows:
            QMessageBox.information(self, "Нет данных", "Таблица пуста.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Сохранить Excel", str(settings.EXPORTS_DIR / "leads.xlsx"),
            "Книга Excel (*.xlsx)",
        )
        if not path:
            return
        doubtful = self.companies.list_all(processing_status="doubtful")
        export_excel(rows, path, stats=self.last_stats, doubtful_rows=doubtful)
        QMessageBox.information(self, "Экспорт завершён", f"Файл сохранён:\n{path}")

    def _export_csv(self) -> None:
        rows = self._rows_for_export()
        if not rows:
            QMessageBox.information(self, "Нет данных", "Таблица пуста.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Сохранить CSV", str(settings.EXPORTS_DIR / "leads.csv"),
            "CSV-файл (*.csv)",
        )
        if not path:
            return
        export_csv(rows, path)
        QMessageBox.information(self, "Экспорт завершён", f"Файл сохранён:\n{path}")

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt-имя)
        if self.worker is not None:
            self.worker.request_stop()
        if self.thread is not None:
            self.thread.quit()
            self.thread.wait(3000)
        self.conn.close()
        super().closeEvent(event)

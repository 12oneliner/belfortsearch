"""Тесты слоя интерфейса без показа окон (offscreen).

Qt запускается в режиме offscreen, поэтому тесты проходят на машине без
дисплея и не открывают окон.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from app.results_table import (  # noqa: E402
    COLUMNS,
    STATUS_LABELS,
    WEBSITE_STATUS_LABELS,
    ResultsTableModel,
)
from app.workers import SearchWorker  # noqa: E402
from database.models import Company  # noqa: E402
from sources.base import BaseSource, RawCompany, SourceStatus  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _company(**overrides) -> Company:
    data = dict(
        id="c1", name="ООО Потолки Юг", niche="натяжные потолки",
        city="Ростов-на-Дону", phone="+7 863 111-22-33", score=77,
        website_status="NO_WEBSITE_CONFIRMED", processing_status="fit",
        score_explanation="Без сайта: 30/30 — подтверждено",
    )
    data.update(overrides)
    return Company(**data)


# ----------------------------- модель таблицы -----------------------------

def test_table_model_dimensions(qapp):
    model = ResultsTableModel([_company(), _company(id="c2", name="Б")])
    assert model.rowCount() == 2
    assert model.columnCount() == len(COLUMNS)


def test_table_model_shows_russian_headers(qapp):
    from PySide6.QtCore import Qt

    model = ResultsTableModel([])
    headers = [
        model.headerData(i, Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole)
        for i in range(model.columnCount())
    ]
    assert "Название" in headers
    assert "Статус сайта" in headers
    assert "Балл" in headers


def test_table_model_translates_statuses(qapp):
    from PySide6.QtCore import Qt

    model = ResultsTableModel([_company()])
    website_col = [i for i, c in enumerate(COLUMNS) if c[0] == "website_status"][0]
    status_col = [i for i, c in enumerate(COLUMNS) if c[0] == "processing_status"][0]

    website_value = model.data(model.index(0, website_col), Qt.ItemDataRole.DisplayRole)
    status_value = model.data(model.index(0, status_col), Qt.ItemDataRole.DisplayRole)

    assert website_value == WEBSITE_STATUS_LABELS["NO_WEBSITE_CONFIRMED"]
    assert status_value == STATUS_LABELS["fit"]


def test_table_model_missing_values_shown_as_dash(qapp):
    """Нет данных — показываем «—», ничего не выдумываем (ТЗ п.7)."""
    from PySide6.QtCore import Qt

    model = ResultsTableModel([_company(phone=None, rating=None, address=None)])
    phone_col = [i for i, c in enumerate(COLUMNS) if c[0] == "phone"][0]
    rating_col = [i for i, c in enumerate(COLUMNS) if c[0] == "rating"][0]

    assert model.data(model.index(0, phone_col), Qt.ItemDataRole.DisplayRole) == "—"
    assert model.data(model.index(0, rating_col), Qt.ItemDataRole.DisplayRole) == "—"


def test_table_model_score_tooltip_shows_explanation(qapp):
    from PySide6.QtCore import Qt

    model = ResultsTableModel([_company()])
    score_col = [i for i, c in enumerate(COLUMNS) if c[0] == "score"][0]
    tooltip = model.data(model.index(0, score_col), Qt.ItemDataRole.ToolTipRole)
    assert "Без сайта" in tooltip


def test_table_model_set_companies_replaces_rows(qapp):
    model = ResultsTableModel([_company()])
    model.set_companies([_company(id="c2"), _company(id="c3")])
    assert model.rowCount() == 2
    assert model.company_at(0).id == "c2"
    assert model.company_at(99) is None


def test_table_model_empty_is_valid(qapp):
    model = ResultsTableModel([])
    assert model.rowCount() == 0
    assert model.companies() == []


# ----------------------------- воркер -----------------------------

class FixedSource(BaseSource):
    name = "fixed"

    def __init__(self, items):
        self.items = items

    def is_available(self):
        return True

    def search(self, niche, city, limit):
        return list(self.items[:limit]), SourceStatus(
            source_name=self.name, found=len(self.items), processed=len(self.items)
        )


def test_worker_emits_finished_with_stats(qapp, tmp_path):
    raw = RawCompany(source_name="fixed", name="Фирма", city="Казань",
                     phone="+7 843 000-00-00", website_url=None)
    worker = SearchWorker(
        niche="окна", city="Казань", sources=[FixedSource([raw])],
        target_leads=5, db_path=str(tmp_path / "w.db"),
    )

    received: list[dict] = []
    worker.finished.connect(received.append)
    worker.run()  # синхронно: поток не нужен для проверки логики

    assert len(received) == 1
    assert received[0]["found"] == 1
    assert received[0]["unique"] == 1


def test_worker_stop_request_preserves_results(qapp, tmp_path):
    raws = [
        RawCompany(source_name="fixed", name=f"Фирма {i}", city="Казань",
                   phone=f"+7 843 000-{i:02d}-{i:02d}", website_url=None)
        for i in range(5)
    ]
    worker = SearchWorker(
        niche="окна", city="Казань", sources=[FixedSource(raws)],
        target_leads=100, db_path=str(tmp_path / "w2.db"),
    )
    worker.request_stop()  # остановка до начала обработки

    stats: list[dict] = []
    worker.finished.connect(stats.append)
    worker.run()

    assert len(stats) == 1
    assert stats[0]["found"] == 0  # обработка прервана до первой записи


def test_worker_reports_failure(qapp, tmp_path):
    class BrokenSource(BaseSource):
        name = "broken"

        def is_available(self):
            return True

        def search(self, niche, city, limit):
            raise RuntimeError("источник сломан")

    worker = SearchWorker(
        niche="окна", city="Казань", sources=[BrokenSource()],
        target_leads=5, db_path=str(tmp_path / "w3.db"),
    )

    finished: list[dict] = []
    worker.finished.connect(finished.append)
    worker.run()

    # Ошибка одного источника не ломает запуск: он завершается со статистикой.
    assert len(finished) == 1
    assert finished[0]["found"] == 0


def test_worker_messages_are_russian(qapp, tmp_path):
    worker = SearchWorker(
        niche="окна", city="Казань", sources=[FixedSource([])],
        target_leads=5, db_path=str(tmp_path / "w4.db"),
    )
    messages: list[str] = []
    worker.message.connect(messages.append)
    worker.run()

    assert any("Поиск" in m for m in messages)

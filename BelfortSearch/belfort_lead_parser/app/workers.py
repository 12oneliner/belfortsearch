"""Фоновые задачи интерфейса (ТЗ п.4: интерфейс не должен зависать)."""

from __future__ import annotations

from PySide6.QtCore import QObject, QThread, Signal

from core.search_manager import SearchManager
from sources.base import BaseSource


class SearchWorker(QObject):
    """Выполняет поиск в отдельном потоке и сообщает о прогрессе сигналами."""

    progress = Signal(dict)       # счётчики по ходу работы
    message = Signal(str)         # понятный статус для пользователя
    finished = Signal(dict)       # итоговая сводка запуска
    failed = Signal(str)          # ошибка, не позволившая завершить запуск

    def __init__(
        self,
        niche: str,
        city: str,
        sources: list[BaseSource],
        target_leads: int,
        limit_per_source: int = 100,
        db_path=None,
    ) -> None:
        super().__init__()
        self.niche = niche
        self.city = city
        self.sources = sources
        self.target_leads = target_leads
        self.limit_per_source = limit_per_source
        self.db_path = db_path
        self._stop_requested = False
        self._manager: SearchManager | None = None

    def request_stop(self) -> None:
        """Просит остановить поиск. Уже полученные результаты сохраняются."""
        self._stop_requested = True
        self.message.emit("Остановка поиска: сохраняем полученные результаты…")

    def run(self) -> None:
        try:
            self._manager = SearchManager(
                db_path=self.db_path,
                cancel_check=lambda: self._stop_requested,
            )
            self.message.emit(
                f"Поиск: «{self.niche}» в городе {self.city}. "
                f"Источников: {len(self.sources)}"
            )
            stats = self._manager.run(
                niche=self.niche,
                city=self.city,
                sources=self.sources,
                target_leads=self.target_leads,
                limit_per_source=self.limit_per_source,
            )
            self.progress.emit(dict(self._manager.counters))
            if self._stop_requested:
                self.message.emit("Поиск остановлен пользователем. Результаты сохранены.")
            self.finished.emit(stats)
        except Exception as exc:  # не маскируем: сообщаем пользователю
            self.failed.emit(str(exc))
        finally:
            if self._manager is not None:
                self._manager.close()


def start_worker(worker: SearchWorker) -> QThread:
    """Запускает воркер в новом потоке и возвращает поток (его нужно хранить)."""
    thread = QThread()
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.finished.connect(thread.quit)
    worker.failed.connect(thread.quit)
    thread.start()
    return thread

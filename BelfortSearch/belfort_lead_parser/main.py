"""Точка входа Belfort Lead Parser: GUI (PySide6) или --cli для проверки базы."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import settings  # noqa: E402
from database.connection import init_db  # noqa: E402
from database.repository import CompanyRepository, RunRepository  # noqa: E402
from utils.logging_config import setup_logging  # noqa: E402


def run_cli_report() -> int:
    """Консольный режим: проверяет базу (нужен для тестов и диагностики)."""
    logger = setup_logging()
    conn = init_db()
    try:
        companies = CompanyRepository(conn).count()
        runs = len(RunRepository(conn).list_recent(limit=1000))
        logger.info("%s v%s", settings.APP_NAME, settings.APP_VERSION)
        logger.info("База: %s", settings.DB_PATH)
        logger.info("Компаний: %s; запусков: %s", companies, runs)
    finally:
        conn.close()
    return 0


def run_gui() -> int:
    """Запуск графического интерфейса."""
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:
        print("PySide6 не установлен. Выполните: pip install -r requirements.txt")
        return 1

    from app.main_window import MainWindow

    application = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return application.exec()


def main() -> int:
    settings.ensure_dirs()
    parser = argparse.ArgumentParser(description="Belfort Lead Parser")
    parser.add_argument("--cli", action="store_true",
                        help="консольный режим (проверка базы без окна)")
    args = parser.parse_args()

    if args.cli:
        return run_cli_report()
    return run_gui()


if __name__ == "__main__":
    raise SystemExit(main())

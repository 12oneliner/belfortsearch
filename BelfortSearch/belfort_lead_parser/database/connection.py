"""Подключение к SQLite и применение миграций (ТЗ п.13)."""

from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from config import settings

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def connect(db_path: Path | str | None = None) -> sqlite3.Connection:
    """Открывает соединение с включёнными внешними ключами и WAL."""
    path = Path(db_path) if db_path is not None else settings.DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def _applied_versions(conn: sqlite3.Connection) -> set[int]:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
    ).fetchone()
    if row is None:
        return set()
    return {r[0] for r in conn.execute("SELECT version FROM schema_migrations")}


def apply_migrations(conn: sqlite3.Connection) -> list[int]:
    """Применяет непримененные .sql миграции по возрастанию. Возвращает версии."""
    applied = _applied_versions(conn)
    executed: list[int] = []

    for sql_file in sorted(MIGRATIONS_DIR.glob("*.sql")):
        try:
            version = int(sql_file.name.split("_", 1)[0])
        except ValueError:
            logger.warning("Пропущен файл миграции с некорректным именем: %s", sql_file.name)
            continue
        if version in applied:
            continue

        sql = sql_file.read_text(encoding="utf-8")
        with conn:  # транзакция
            conn.executescript(sql)
            conn.execute(
                "INSERT OR REPLACE INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                (version, datetime.now(timezone.utc).isoformat()),
            )
        executed.append(version)
        logger.info("Применена миграция %s", sql_file.name)

    return executed


def init_db(db_path: Path | str | None = None) -> sqlite3.Connection:
    """Создаёт базу при первом запуске и применяет миграции."""
    conn = connect(db_path)
    apply_migrations(conn)
    return conn


@contextmanager
def session(db_path: Path | str | None = None) -> Iterator[sqlite3.Connection]:
    """Контекстный менеджер: база инициализирована, соединение закрывается."""
    conn = init_db(db_path)
    try:
        yield conn
    finally:
        conn.close()


def backup_database(target_path: Path | str, db_path: Path | str | None = None) -> Path:
    """Создаёт резервную копию базы средствами SQLite (безопасно при открытой базе)."""
    source = Path(db_path) if db_path is not None else settings.DB_PATH
    target = Path(target_path)
    target.parent.mkdir(parents=True, exist_ok=True)

    src = connect(source)
    try:
        dst = sqlite3.connect(target)
        try:
            with dst:
                src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()

    logger.info("Резервная копия базы создана: %s", target)
    return target


def restore_database(backup_path: Path | str, db_path: Path | str | None = None) -> Path:
    """Восстанавливает базу из резервной копии средствами SQLite backup API.

    Содержимое целевой базы заменяется полностью. В отличие от копирования файла,
    способ безопасен при открытых соединениях и не ломает WAL-файлы.
    """
    source = Path(backup_path)
    if not source.exists():
        raise FileNotFoundError(f"Файл резервной копии не найден: {source}")

    target = Path(db_path) if db_path is not None else settings.DB_PATH
    target.parent.mkdir(parents=True, exist_ok=True)

    src = sqlite3.connect(source)
    try:
        dst = connect(target)
        try:
            with dst:
                src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()

    logger.info("База восстановлена из %s", source)
    return target

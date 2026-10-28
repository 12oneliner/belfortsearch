"""Репозитории доступа к данным (ТЗ п.13)."""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import asdict, fields
from datetime import datetime, timezone

from database.models import Company, Contact, Run, WebsiteCheck


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id() -> str:
    return uuid.uuid4().hex


def _columns(cls) -> list[str]:
    return [f.name for f in fields(cls)]


def _row_to(cls, row: sqlite3.Row):
    data = {k: row[k] for k in row.keys() if k in set(_columns(cls))}
    return cls(**data)


class CompanyRepository:
    """CRUD по компаниям + история изменений."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def add(self, company: Company) -> Company:
        if not company.id:
            company.id = new_id()
        if not company.first_seen:
            company.first_seen = now_iso()
        if not company.last_checked:
            company.last_checked = company.first_seen

        data = asdict(company)
        cols = list(data)
        placeholders = ", ".join("?" for _ in cols)
        with self.conn:
            self.conn.execute(
                f"INSERT INTO companies ({', '.join(cols)}) VALUES ({placeholders})",
                [data[c] for c in cols],
            )
        return company

    def get(self, company_id: str) -> Company | None:
        row = self.conn.execute(
            "SELECT * FROM companies WHERE id = ?", (company_id,)
        ).fetchone()
        return _row_to(Company, row) if row else None

    def update(self, company_id: str, **changes) -> Company | None:
        """Обновляет поля и пишет историю изменений по каждому полю."""
        current = self.get(company_id)
        if current is None:
            return None

        allowed = set(_columns(Company)) - {"id"}
        changes = {k: v for k, v in changes.items() if k in allowed}
        if not changes:
            return current

        changes.setdefault("last_checked", now_iso())
        assignments = ", ".join(f"{k} = ?" for k in changes)
        values = list(changes.values()) + [company_id]

        with self.conn:
            self.conn.execute(
                f"UPDATE companies SET {assignments} WHERE id = ?", values
            )
            stamp = now_iso()
            for field_name, new_value in changes.items():
                old_value = getattr(current, field_name)
                if old_value == new_value:
                    continue
                self.conn.execute(
                    "INSERT INTO history (id, company_id, field_name, old_value, new_value,"
                    " changed_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        new_id(),
                        company_id,
                        field_name,
                        None if old_value is None else str(old_value),
                        None if new_value is None else str(new_value),
                        stamp,
                    ),
                )
        return self.get(company_id)

    def delete(self, company_id: str) -> bool:
        """Удаляет компанию и все связанные данные (ТЗ п.18)."""
        with self.conn:
            cursor = self.conn.execute("DELETE FROM companies WHERE id = ?", (company_id,))
        return cursor.rowcount > 0

    def list_all(
        self,
        *,
        city: str | None = None,
        niche: str | None = None,
        processing_status: str | None = None,
        website_status: str | None = None,
        min_score: int | None = None,
    ) -> list[Company]:
        """Возвращает компании по фильтрам, по убыванию итогового балла."""
        query = "SELECT * FROM companies WHERE 1=1"
        params: list = []
        for column, value in (
            ("city", city),
            ("niche", niche),
            ("processing_status", processing_status),
            ("website_status", website_status),
        ):
            if value is not None:
                query += f" AND {column} = ?"
                params.append(value)
        if min_score is not None:
            query += " AND score >= ?"
            params.append(min_score)
        query += " ORDER BY score DESC, name ASC"

        rows = self.conn.execute(query, params).fetchall()
        return [_row_to(Company, row) for row in rows]

    def find_by_normalized_phone(self, normalized_phone: str) -> list[Company]:
        if not normalized_phone:
            return []
        rows = self.conn.execute(
            "SELECT * FROM companies WHERE normalized_phone = ?", (normalized_phone,)
        ).fetchall()
        return [_row_to(Company, row) for row in rows]

    def count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM companies").fetchone()[0]

    def history(self, company_id: str) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM history WHERE company_id = ? ORDER BY changed_at",
            (company_id,),
        ).fetchall()


class ContactRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def add(self, contact: Contact) -> Contact:
        if not contact.id:
            contact.id = new_id()
        data = asdict(contact)
        cols = list(data)
        with self.conn:
            self.conn.execute(
                f"INSERT INTO contacts ({', '.join(cols)}) "
                f"VALUES ({', '.join('?' for _ in cols)})",
                [data[c] for c in cols],
            )
        return contact

    def list_for_company(self, company_id: str) -> list[Contact]:
        rows = self.conn.execute(
            "SELECT * FROM contacts WHERE company_id = ?", (company_id,)
        ).fetchall()
        return [_row_to(Contact, row) for row in rows]


class WebsiteCheckRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def add(self, check: WebsiteCheck) -> WebsiteCheck:
        if not check.id:
            check.id = new_id()
        if not check.checked_at:
            check.checked_at = now_iso()
        data = asdict(check)
        cols = list(data)
        with self.conn:
            self.conn.execute(
                f"INSERT INTO website_checks ({', '.join(cols)}) "
                f"VALUES ({', '.join('?' for _ in cols)})",
                [data[c] for c in cols],
            )
        return check

    def list_for_company(self, company_id: str) -> list[WebsiteCheck]:
        rows = self.conn.execute(
            "SELECT * FROM website_checks WHERE company_id = ? ORDER BY checked_at",
            (company_id,),
        ).fetchall()
        return [_row_to(WebsiteCheck, row) for row in rows]


class RunRepository:
    """История запусков (ТЗ п.15)."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def start(self, run: Run) -> Run:
        if not run.id:
            run.id = new_id()
        if not run.started_at:
            run.started_at = now_iso()
        data = asdict(run)
        cols = list(data)
        with self.conn:
            self.conn.execute(
                f"INSERT INTO runs ({', '.join(cols)}) "
                f"VALUES ({', '.join('?' for _ in cols)})",
                [data[c] for c in cols],
            )
        return run

    def finish(self, run_id: str, **stats) -> Run | None:
        allowed = set(_columns(Run)) - {"id", "started_at"}
        stats = {k: v for k, v in stats.items() if k in allowed}
        stats.setdefault("finished_at", now_iso())
        assignments = ", ".join(f"{k} = ?" for k in stats)
        with self.conn:
            self.conn.execute(
                f"UPDATE runs SET {assignments} WHERE id = ?",
                list(stats.values()) + [run_id],
            )
        return self.get(run_id)

    def get(self, run_id: str) -> Run | None:
        row = self.conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        return _row_to(Run, row) if row else None

    def list_recent(self, limit: int = 50) -> list[Run]:
        rows = self.conn.execute(
            "SELECT * FROM runs ORDER BY started_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [_row_to(Run, row) for row in rows]

    def add_error(self, run_id: str | None, source_name: str, message: str) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT INTO source_errors (id, run_id, source_name, message, created_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (new_id(), run_id, source_name, message, now_iso()),
            )

    def list_errors(self, run_id: str) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM source_errors WHERE run_id = ? ORDER BY created_at", (run_id,)
        ).fetchall()

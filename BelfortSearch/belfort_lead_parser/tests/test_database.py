"""Тесты базы данных (ТЗ п.19: пункты 9-10, 14)."""

from __future__ import annotations

import pytest

from database.connection import (
    backup_database,
    connect,
    restore_database,
)
from database.models import Company, Contact, Run, WebsiteCheck
from database.repository import (
    CompanyRepository,
    ContactRepository,
    RunRepository,
    WebsiteCheckRepository,
)


@pytest.fixture
def conn(tmp_path):
    """Изолированная временная база: инициализация + миграции при каждом тесте."""
    db_path = tmp_path / "test.db"
    connection = connect(db_path)
    from database.connection import apply_migrations

    apply_migrations(connection)
    yield connection
    connection.close()


def _company(**overrides) -> Company:
    data = dict(
        id="",
        name="Потолки Юг",
        niche="натяжные потолки",
        city="Ростов-на-Дону",
        phone="+7 (863) 111-22-33",
        normalized_phone="78631112233",
        normalized_name="потолки юг",
        processing_status="found",
    )
    data.update(overrides)
    return Company(**data)


def test_save_and_read_company(conn):
    repo = CompanyRepository(conn)
    saved = repo.add(_company())
    assert saved.id

    loaded = repo.get(saved.id)
    assert loaded is not None
    assert loaded.name == "Потолки Юг"
    assert loaded.phone == "+7 (863) 111-22-33"
    assert loaded.normalized_phone == "78631112233"


def test_update_writes_history(conn):
    repo = CompanyRepository(conn)
    saved = repo.add(_company())

    updated = repo.update(saved.id, score=85, processing_status="fit")
    assert updated.score == 85

    history = repo.history(saved.id)
    changed = {row["field_name"] for row in history}
    assert "score" in changed
    assert "processing_status" in changed
    assert "last_checked" in changed


def test_update_unknown_company_returns_none(conn):
    repo = CompanyRepository(conn)
    assert repo.update("no-such-id", score=10) is None


def test_delete_company_removes_contacts(conn):
    companies = CompanyRepository(conn)
    contacts = ContactRepository(conn)
    saved = companies.add(_company())
    contacts.add(
        Contact(id="", company_id=saved.id, contact_type="phone",
                value="+78631112233", source="карточка")
    )
    assert len(contacts.list_for_company(saved.id)) == 1

    assert companies.delete(saved.id) is True
    assert companies.get(saved.id) is None
    assert contacts.list_for_company(saved.id) == []


def test_list_filters_and_ordering(conn):
    repo = CompanyRepository(conn)
    repo.add(_company(name="Альфа", score=60, city="Казань"))
    repo.add(_company(name="Бета", score=90, city="Казань"))
    repo.add(_company(name="Гамма", score=80, city="Ростов-на-Дону"))

    all_rows = repo.list_all()
    assert [c.name for c in all_rows] == ["Бета", "Гамма", "Альфа"]

    kazan = repo.list_all(city="Казань")
    assert {c.name for c in kazan} == {"Альфа", "Бета"}

    strong = repo.list_all(min_score=80)
    assert {c.name for c in strong} == {"Бета", "Гамма"}


def test_find_by_normalized_phone(conn):
    repo = CompanyRepository(conn)
    repo.add(_company())
    found = repo.find_by_normalized_phone("78631112233")
    assert len(found) == 1
    assert repo.find_by_normalized_phone("") == []


def test_contacts_and_website_checks(conn):
    companies = CompanyRepository(conn)
    contacts = ContactRepository(conn)
    checks = WebsiteCheckRepository(conn)

    saved = companies.add(_company())
    contacts.add(
        Contact(
            id="",
            company_id=saved.id,
            contact_type="person",
            value="Иван Петров",
            role="директор",
            source="карточка",
            confidence="medium",
        )
    )
    checks.add(
        WebsiteCheck(
            id="",
            company_id=saved.id,
            status="UNCERTAIN",
            evidence="найден каталог, сайт не подтверждён",
        )
    )

    assert len(contacts.list_for_company(saved.id)) == 1
    stored_checks = checks.list_for_company(saved.id)
    assert len(stored_checks) == 1
    assert stored_checks[0].status == "UNCERTAIN"


def test_run_lifecycle_and_errors(conn):
    runs = RunRepository(conn)
    run = runs.start(Run(id="", niche="окна", city="Казань", sources='["csv_import"]'))
    assert run.started_at

    finished = runs.finish(run.id, found=10, unique_count=8, quality_leads=3)
    assert finished.finished_at is not None
    assert finished.quality_leads == 3

    runs.add_error(run.id, "csv_import", "файл не найден")
    errors = runs.list_errors(run.id)
    assert len(errors) == 1
    assert errors[0]["source_name"] == "csv_import"

    recent = runs.list_recent()
    assert len(recent) == 1


def test_backup_and_restore(tmp_path, conn):
    companies = CompanyRepository(conn)
    saved = companies.add(_company(name="До бэкапа"))

    backup_path = tmp_path / "backup.db"
    backup_database(backup_path, tmp_path / "test.db")

    companies.update(saved.id, name="После бэкапа")
    assert companies.get(saved.id).name == "После бэкапа"

    restore_database(backup_path, tmp_path / "test.db")
    conn2 = connect(tmp_path / "test.db")
    restored = CompanyRepository(conn2).get(saved.id)
    conn2.close()
    assert restored.name == "До бэкапа"


def test_empty_results_ok(conn):
    assert CompanyRepository(conn).list_all() == []
    assert RunRepository(conn).list_recent() == []

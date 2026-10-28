"""Тесты источника CSV-импорта и SearchManager (без реальной сети)."""

from core.contact_finder import ContactEvidence
from core.search_manager import SearchManager
from core.website_checker import (
    SITE_KIND_UNKNOWN,
    WebsiteCheckResult,
    WebsiteChecker,
)
from database.connection import init_db
from database.models import Contact
from sources.base import BaseSource, RawCompany, SourceStatus
from sources.csv_import import CsvImportSource, _map_headers


# ----------------------------- CSV-импорт -----------------------------

def _make_csv(tmp_path, content: str, name: str = "leads.csv") -> str:
    path = tmp_path / name
    path.write_text(content, encoding="utf-8-sig")
    return str(path)


def test_csv_import_reads_semicolon_file(tmp_path):
    content = (
        "Название;Город;Адрес;Телефон;Сайт;Ссылка на карточку;Рейтинг;Количество отзывов;Ниша\n"
        'ООО "Потолки Юг";Ростов-на-Дону;ул. Ленина 1;+7 863 111-22-33;;https://2gis.ru/1;4.7;12;натяжные потолки\n'
        "Иванов И.П.;Казань;ул. Пушкина 2;+7 843 000-00-00;https://remont.kz;;;ремонт квартир\n"
    )
    source = CsvImportSource(_make_csv(tmp_path, content))
    items, status = source.search("натяжные потолки", "Ростов-на-Дону", limit=100)
    assert status.available
    assert len(items) == 1
    assert items[0].name == 'ООО "Потолки Юг"'
    assert items[0].city == "Ростов-на-Дону"
    assert items[0].phone == "+7 863 111-22-33"
    assert items[0].card_url == "https://2gis.ru/1"
    assert items[0].rating == 4.7
    assert items[0].reviews_count == 12


def test_csv_import_reads_comma_file(tmp_path):
    content = 'Название,Город,Телефон\n"Фирма, плюс",Москва,"+7 495 000-00-00"\n'
    source = CsvImportSource(_make_csv(tmp_path, content))
    items, status = source.search("любая", "Москва", limit=100)
    assert status.available
    assert len(items) == 1
    assert items[0].name == "Фирма, плюс"


def test_csv_import_filters_by_city(tmp_path):
    content = "Название;Город\nА;Москва\nБ;Казань\n"
    source = CsvImportSource(_make_csv(tmp_path, content))
    items, _status = source.search("любая", "Казань", limit=100)
    assert len(items) == 1
    assert items[0].name == "Б"


def test_csv_import_missing_name_column_fails_gracefully(tmp_path):
    content = "Город;Телефон\nМосква;+7\n"
    source = CsvImportSource(_make_csv(tmp_path, content))
    items, status = source.search("любая", "Москва", limit=100)
    assert not status.available
    assert items == []
    assert any("Название" in err for err in status.errors)


def test_csv_import_missing_file():
    source = CsvImportSource("/nonexistent/path.csv")
    items, status = source.search("любая", "Москва", limit=100)
    assert not status.available
    assert items == []


def test_csv_import_no_file_selected():
    source = CsvImportSource(None)
    items, status = source.search("любая", "Москва", limit=100)
    assert not status.available
    assert items == []


def test_column_aliases_normalized():
    headers = ["Название Компании", "ГОРОД", " Телефон "]
    mapping = _map_headers(headers)
    assert mapping["Название Компании"] == "name"
    assert mapping["ГОРОД"] == "city"
    assert mapping[" Телефон "] == "phone"


# ----------------------------- фейковые источники -----------------------------

class FixedSource(BaseSource):
    name = "fixed"

    def __init__(self, items):
        self.items = items
        self.available = True

    def is_available(self):
        return self.available

    def search(self, niche, city, limit):
        return list(self.items[:limit]), SourceStatus(
            source_name=self.name, found=len(self.items), processed=len(self.items)
        )


# ----------------------------- SearchManager -----------------------------

def _make_manager(tmp_path):
    db_path = tmp_path / "sm.db"
    return SearchManager(db_path=str(db_path))


def _website_confirmed():
    """Стаб: все проверки возвращают каталог/соцсеть — собственный сайт не найден."""

    def search_fn(query):
        return [
            {"url": "https://spravgoroda.ru/org/111", "title": "Справочник организаций"},
            {"url": "https://vk.com/nenashe", "title": "Чужая страница | ВКонтакте"},
        ]

    return WebsiteChecker(search_fn=search_fn)


class OwnerHighFinder:
    """Стаб контактов: владелец с высокой достоверностью."""

    def __init__(self, company_id=""):
        self._company_id = company_id

    def find(self, company):
        contact = Contact(
            id="", company_id=company.id, contact_type="person", value="Иван Петров",
            role="директор", source="карточка", confidence="high",
        )
        return [ContactEvidence(contact=contact, proof_excerpt="директор")]


def test_search_manager_end_to_end(tmp_path):
    manager = SearchManager(
        db_path=str(tmp_path / "sm.db"),
        website_checker=_website_confirmed(),
        contact_finder=OwnerHighFinder(),
    )
    raw = RawCompany(
        source_name="fixed", name="ООО Потолки Юг", city="Ростов-на-Дону",
        niche="натяжные потолки", phone="+7 863 111-22-33",
        address="ул. Ленина 1", website_url=None,
        rating=4.7, reviews_count=30,
    )
    stats = manager.run(
        niche="натяжные потолки", city="Ростов-на-Дону",
        sources=[FixedSource([raw])], target_leads=50, limit_per_source=50,
    )

    assert stats["found"] == 1
    assert stats["unique"] == 1
    assert stats["checked_websites"] == 1
    assert stats["confirmed_no_website"] == 1
    assert stats["quality_leads"] == 1
    assert stats["run_id"] is not None

    saved = manager.companies.list_all()
    assert len(saved) == 1
    # 30 (сайт не найден) + 20 (30 отзывов) + 12 (рейтинг 4.7) + 10 (владелец,
    # высокая достоверность) + 5 (телефон + адрес) = 77. Свежесть/фото/соцсети
    # неизвестны.
    assert saved[0].score == 77
    assert saved[0].processing_status == "fit"

    run_row = manager.runs.get(stats["run_id"])
    assert run_row is not None
    assert run_row.quality_leads == 1
    manager.close()


def test_search_manager_duplicate_is_not_counted_twice(tmp_path):
    manager = SearchManager(
        db_path=str(tmp_path / "sm.db"),
        website_checker=_website_confirmed(),
        contact_finder=OwnerHighFinder(),
    )
    raw = RawCompany(
        source_name="fixed", name="ООО Потолки Юг", city="Ростов-на-Дону",
        phone="+7 863 111-22-33", website_url=None,
    )

    stats = manager.run(
        niche="окна", city="Ростов-на-Дону",
        sources=[FixedSource([raw, raw])], target_leads=50, limit_per_source=50,
    )
    companies = manager.companies.list_all()
    assert len(companies) == 1
    assert stats["unique"] == 1
    assert stats["found"] == 2
    manager.close()


def test_source_unavailable_continues_run(tmp_path):
    manager = _make_manager(tmp_path)
    source = FixedSource([])
    source.available = False

    stats = manager.run(niche="окна", city="Казань", sources=[source],
                        target_leads=50, limit_per_source=50)
    assert stats["found"] == 0
    errors = manager.runs.list_errors(stats["run_id"])
    assert len(errors) == 1
    assert "доступен" in errors[0]["message"]
    manager.close()


def test_target_leads_stops_search(tmp_path):
    manager = SearchManager(
        db_path=str(tmp_path / "sm.db"),
        website_checker=_website_confirmed(),
        contact_finder=OwnerHighFinder(),
    )
    raws = [
        RawCompany(source_name="fixed", name=f"Фирма {i}", city="Казань",
                   phone=f"+7 843 000-{i:02d}-{i:02d}", website_url=None)
        for i in range(10)
    ]
    stats = manager.run(niche="окна", city="Казань", sources=[FixedSource(raws)],
                        target_leads=3, limit_per_source=100)
    assert stats["quality_leads"] == 3
    assert stats["unique"] == 3
    manager.close()


def test_stop_preserves_saved_results(tmp_path):
    manager = SearchManager(
        db_path=str(tmp_path / "sm.db"),
        website_checker=_website_confirmed(),
        contact_finder=OwnerHighFinder(),
    )
    raw = RawCompany(
        source_name="fixed", name="ООО Потолки Юг", city="Ростов-на-Дону",
        phone="+7 863 111-22-33", website_url=None,
    )

    # Остановка после первой обработанной записи: cancel_check включает флаг
    # внутри обёртки _process_raw.
    manager._stopping = False

    orig_process = manager._process_raw

    def wrapping(raw_item, run_id, existing, niche, city):
        result = orig_process(raw_item, run_id, existing, niche, city)
        manager.cancel_check = lambda: True
        return result

    manager._process_raw = wrapping
    raws = [raw] + [
        RawCompany(source_name="fixed", name=f"Фирма {i}", city="Ростов-на-Дону",
                   phone=f"+7 863 111-{i:02d}-{i:02d}", website_url=None)
        for i in range(5)
    ]
    stats = manager.run(niche="потолки", city="Ростов-на-Дону",
                        sources=[FixedSource(raws)], target_leads=50,
                        limit_per_source=50)
    assert stats["unique"] == 1  # сохранена именно первая, уже обработанная запись
    saved = manager.companies.list_all()
    assert len(saved) == 1
    assert saved[0].name == "ООО Потолки Юг"
    manager.close()


def test_repeat_run_merges_again_as_duplicates(tmp_path):
    """Повторный запуск не плодит записи (ТЗ п.19 п.15)."""
    db = str(tmp_path / "sm.db")
    raw = RawCompany(
        source_name="fixed", name="ООО Потолки Юг", city="Ростов-на-Дону",
        phone="+7 863 111-22-33", website_url=None,
    )
    first = SearchManager(
        db_path=db, website_checker=_website_confirmed(),
        contact_finder=OwnerHighFinder(),
    )
    first.run(niche="потолки", city="Ростов-на-Дону",
              sources=[FixedSource([raw])], target_leads=50, limit_per_source=50)
    first.close()

    second = SearchManager(
        db_path=db, website_checker=_website_confirmed(),
        contact_finder=OwnerHighFinder(),
    )
    second.run(niche="потолки", city="Ростов-на-Дону",
               sources=[FixedSource([raw])], target_leads=50, limit_per_source=50)
    companies = second.companies.list_all()
    second.close()

    assert len(companies) == 1


def test_empty_source_run_ok(tmp_path):
    manager = _make_manager(tmp_path)
    stats = manager.run(niche="окна", city="Казань", sources=[FixedSource([])],
                        target_leads=50, limit_per_source=50)
    assert stats["found"] == 0
    assert stats["quality_leads"] == 0
    manager.close()

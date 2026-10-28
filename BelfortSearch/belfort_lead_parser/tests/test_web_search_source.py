"""Тесты источника из веб-поиска (без реальной сети)."""

from sources.web_search_source import (
    WebSearchSource,
    _is_aggregator,
    extract_company_name,
)


def _hits_by_query(mapping: dict) -> callable:
    def search(query: str, limit: int) -> list[dict]:
        return list(mapping.get(query, []))
    return search


# ----------------------------- название из заголовка -----------------------------

def test_extract_company_name_from_title():
    niche, city = "натяжные потолки", "Москва"
    assert extract_company_name("Потолки Люкс — натяжные потолки в Москве", niche, city) == "Потолки Люкс"
    assert extract_company_name("Потолки Люкс | Купить натяжные потолки", niche, city) == "Потолки Люкс"


def test_extract_company_name_skips_pure_marketing():
    niche, city = "натяжные потолки", "Москва"
    # Весь заголовок — маркетинговый текст: компании тут нет.
    assert extract_company_name("Натяжные потолки в Москве — цены, заказать", niche, city) is None
    assert extract_company_name("", niche, city) is None
    assert extract_company_name(None, niche, city) is None


# ----------------------------- отсеивание агрегаторов -----------------------------

def test_aggregators_filtered():
    assert _is_aggregator("https://profi.ru/remont/potolki-moskva/") is True
    assert _is_aggregator("https://yandex.ru/maps/org/123") is True
    assert _is_aggregator("https://vk.com/potolki_lyuks") is True
    assert _is_aggregator("https://potolki-lyuks.ru") is False
    assert _is_aggregator("https://potolki.tilda.ws") is False


# ----------------------------- источник целиком -----------------------------

def test_web_search_source_finds_companies():
    mapping = {
        "натяжные потолки Москва": [
            {"url": "https://potolki-lyuks.ru", "title": "Потолки Люкс — натяжные потолки в Москве"},
            {"url": "https://profi.ru/remont/potolki-moskva/", "title": "Натяжные потолки Москва — Профи"},
            {"url": "https://potolki-sever.ru", "title": "Потолки Север — натяжные потолки"},
        ],
        "натяжные потолки Москва заказать": [
            {"url": "https://potolki-lyuks.ru", "title": "Потолки Люкс — натяжные потолки в Москве"},
        ],
        "натяжные потолки Москва цены": [],
        "натяжные потолки в Москва компания": [],
        "натяжные потолки Москва контакты": [],
    }
    source = WebSearchSource(search_fn=_hits_by_query(mapping), fetch_phones=False)

    assert source.is_available()
    items, status = source.search("натяжные потолки", "Москва", limit=100)

    # Агрегатор отброшен, дубликат одного сайта — тоже: осталось две компании.
    assert status.available
    assert [i.name for i in items] == ["Потолки Люкс", "Потолки Север"]
    assert items[0].city == "Москва"
    assert items[0].niche == "натяжные потолки"
    assert items[0].website_url == "https://potolki-lyuks.ru"
    # Телефоны/рейтинги выдача не отдаёт — не выдумываем.
    assert items[0].phone is None
    assert items[0].rating is None
    assert items[0].reviews_count is None


def test_web_search_source_limit_stops_queries():
    calls = []

    def search(query: str, limit: int) -> list[dict]:
        calls.append(query)
        return [{"url": f"https://f{i}.ru", "title": f"Фирма {i} — услуги"} for i in range(10)]

    source = WebSearchSource(search_fn=search, fetch_phones=False)
    items, _status = source.search("окна", "Казань", limit=2)
    assert len(items) == 2
    # Дальше первого шаблона не пошли: лимит набран сразу.
    assert len(calls) == 1


def test_web_search_source_network_failure_is_empty_not_crash():
    def boom(query: str, limit: int) -> list[dict]:
        raise ConnectionError("сеть недоступна")

    source = WebSearchSource(search_fn=boom, fetch_phones=False)
    items, status = source.search("окна", "Казань", limit=10)
    assert items == []
    assert status.available


def test_web_search_source_all_marketing_titles_give_nothing():
    mapping = {
        q: [{"url": "https://potolki-lyuks.ru", "title": "Натяжные потолки в Москве — цены, заказать"}]
        for q in (
            "натяжные потолки Москва",
            "натяжные потолки Москва заказать",
            "натяжные потолки Москва цены",
            "натяжные потолки в Москва компания",
            "натяжные потолки Москва контакты",
        )
    }
    source = WebSearchSource(search_fn=_hits_by_query(mapping), fetch_phones=False)
    items, status = source.search("натяжные потолки", "Москва", limit=100)
    assert items == []
    assert status.processed == 0

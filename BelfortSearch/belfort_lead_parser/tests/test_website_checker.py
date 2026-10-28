"""Тесты проверки сайтов (ТЗ п.19: пункты 4-5, 12)."""

from core.website_checker import (
    SITE_KIND_BUILDER,
    SITE_KIND_CATALOG,
    SITE_KIND_OWN,
    SITE_KIND_SOCIAL,
    WebsiteChecker,
    classify_url,
    is_own_website,
    url_linked_to_company,
)
from database.models import (
    WEBSITE_CHECK_FAILED,
    WEBSITE_FOUND,
    WEBSITE_NO_WEBSITE_CONFIRMED,
    WEBSITE_UNCERTAIN,
    Company,
)


def _company(**overrides) -> Company:
    data = dict(id="c1", name="Потолки Юг", niche="натяжные потолки",
                city="Ростов-на-Дону", website_url=None)
    data.update(overrides)
    return Company(**data)


def _search_returning(mapping: dict) -> callable:
    """Фабрика поискового движка: запрос -> список {url, title}."""

    def search(query: str) -> list[dict]:
        return list(mapping.get("default", []))

    return search


def test_card_with_own_website_is_found():
    company = _company(website_url="https://potolki-yug.ru")
    result = WebsiteChecker().check(company)
    assert result.status == WEBSITE_FOUND
    assert result.site_url == "https://potolki-yug.ru"
    assert result.site_kind == SITE_KIND_OWN


def test_card_with_builder_site_is_found_as_builder():
    company = _company(website_url="https://potolki-yug.tilda.ws")
    result = WebsiteChecker().check(company)
    assert result.status == WEBSITE_FOUND
    assert result.site_kind == SITE_KIND_BUILDER


def test_card_with_catalog_link_is_not_a_website():
    """Карточка каталога не считается сайтом (ТЗ п.9)."""
    assert classify_url("https://2gis.ru/rostov/search/потолки") == SITE_KIND_CATALOG
    assert classify_url("https://yandex.ru/maps/org/12345") == SITE_KIND_CATALOG
    assert classify_url("https://www.avito.ru/user/abc") == SITE_KIND_CATALOG
    assert is_own_website("https://2gis.ru/rostov/search/потолки") is False


def test_social_page_is_not_a_website():
    assert classify_url("https://vk.com/potolki_yug") == SITE_KIND_SOCIAL
    assert classify_url("https://t.me/potolki_yug") == SITE_KIND_SOCIAL
    assert is_own_website("https://vk.com/potolki_yug") is False


def test_card_catalog_plus_empty_searches_gives_confirmed_no_website():
    """Карточка-каталог + 3 поиска без собственного сайта → подтверждено."""
    company = _company(website_url="https://2gis.ru/rostov/firm/123")
    search = _search_returning({"default": [
        {"url": "https://2gis.ru/rostov/firm/123", "title": "Потолки Юг — 2ГИС"},
        {"url": "https://vk.com/potolki_yug", "title": "Потолки Юг | ВКонтакте"},
    ]})
    result = WebsiteChecker(search_fn=search).check(company)
    assert result.status == WEBSITE_NO_WEBSITE_CONFIRMED
    assert any("подтверждено" in e for e in result.evidence)


def test_linked_own_website_found_via_search():
    company = _company()
    search = _search_returning({"default": [
        {"url": "https://potolki-yug.ru", "title": "Потолки Юг — натяжные потолки"},
    ]})
    result = WebsiteChecker(search_fn=search).check(company)
    assert result.status == WEBSITE_FOUND
    assert result.site_url == "https://potolki-yug.ru"


def test_suspicious_match_without_link_is_not_a_website():
    """Похожий URL без связи с компанией сайтом не считается."""
    company = _company(name="Потолки Юг")
    search = _search_returning({"default": [
        {"url": "https://potolki-sever.ru", "title": "Потолки Север — другая фирма"},
    ]})
    result = WebsiteChecker(search_fn=search).check(company)
    assert result.status != WEBSITE_FOUND
    assert result.status in (WEBSITE_NO_WEBSITE_CONFIRMED, WEBSITE_UNCERTAIN)


def test_url_linked_by_title():
    company = _company(name="Потолки Юг")
    assert url_linked_to_company("https://potolki-yug.ru", "Потолки Юг — официальный сайт", company)
    assert not url_linked_to_company(
        "https://potolki-sever.ru", "Потолки Север — другая фирма", company)


def test_url_linked_by_domain_token():
    company = _company(name="Ремонт Сервис Дон")
    assert url_linked_to_company("https://remont-don.ru", "Сайт компании", company) is True
    # Обратная проверка: домен без связи всё равно считается подозрительным,
    # но не связанным.
    assert url_linked_to_company("https://okna-moscow.ru", "Окна Москва", company) is False


def test_single_search_with_results_is_not_enough_for_confirmed():
    """Один поиск недостаточен: статус UNCERTAIN, не выдаём за подтверждение."""

    def one_result(query):
        if "официальный сайт" in query:
            return [{"url": "https://2gis.ru/firm/1", "title": "Потолки Юг — 2ГИС"}]
        return []

    result = WebsiteChecker(search_fn=one_result).check(_company())
    assert result.status == WEBSITE_UNCERTAIN


def test_all_searches_failed_gives_check_failed():
    def boom(query):
        raise TimeoutError("сеть недоступна")

    result = WebsiteChecker(search_fn=boom).check(_company())
    assert result.status == WEBSITE_CHECK_FAILED
    assert any("ошибкой" in e for e in result.evidence)


def test_no_search_fn_at_all_gives_uncertain():
    """Без поискового движка данных недостаточно — UNCERTAIN, не CONFIRMED."""
    result = WebsiteChecker().check(_company())
    assert result.status == WEBSITE_UNCERTAIN


def test_network_error_in_one_search_does_not_break_others():
    calls = {"n": 0}

    def flaky(query):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ConnectionError("обрыв")
        return [{"url": "https://2gis.ru/firm/1", "title": "Потолки Юг — 2ГИС"}]

    result = WebsiteChecker(search_fn=flaky).check(_company())
    assert result.status == WEBSITE_NO_WEBSITE_CONFIRMED
    assert any("ошибка" in e for e in result.evidence)

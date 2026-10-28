"""Тесты дедупликации (ТЗ п.12: пункты 6-8)."""

from core.deduplication import MATCH_NONE, compare, find_matches, merge_companies
from database.models import Company
from utils.normalization import normalize_company_name, normalize_phone


def _company(id="c1", name="Потолки Юг", city="Ростов-на-Дону", phone="+7 863 111-22-33",
             address="ул. Ленина 1", card_url="https://2gis.ru/company/123", **overrides):
    """Фикстура компании. Нормализованные ключи считаются из фактических значений."""
    company = Company(
        id=id, name=name, niche="натяжные потолки", city=city, phone=phone,
        address=address, card_url=card_url,
        normalized_phone=normalize_phone(phone),
        normalized_name=normalize_company_name(name),
        **overrides,
    )
    return company


def test_exact_match_by_normalized_phone():
    a = _company()
    b = _company(id="c2", phone="+7 (863) 111-22-33")  # тот же номер, другая запись
    assert compare(a, b).is_exact


def test_exact_match_by_card_url():
    a = _company()
    b = _company(id="c2", card_url="https://2gis.ru/company/123 ")
    assert compare(a, b).is_exact


def test_exact_match_by_name_city_address():
    a = _company()
    b = _company(id="c2", phone="", card_url="")
    assert compare(a, b).is_exact


def test_same_name_same_city_no_address_is_doubtful():
    """Название и город совпадают, адрес не подтверждён — сомнительное (только ручная проверка)."""
    a = _company(phone="", address="", card_url="")
    b = _company(id="c2", phone="", address="", card_url="")
    result = compare(a, b)
    assert result.is_doubtful


def test_similar_name_same_city_is_doubtful():
    a = _company(name="ООО Потолки Юг", phone="", address="", card_url="")
    b = _company(id="c2", name="ООО Потолки-Юг", phone="", address="", card_url="")
    result = compare(a, b)
    assert result.is_doubtful


def test_different_cities_similar_name_is_none():
    """Не объединяем по похожим названиям без города (ТЗ п.12)."""
    a = _company(name="Потолки Юг", city="Казань", phone="", address="", card_url="")
    b = _company(id="c2", name="Потолки Юг", city="Москва", phone="", address="", card_url="")
    assert compare(a, b).kind == MATCH_NONE


def test_different_names_no_match():
    a = _company(name="Потолки Юг", phone="", address="", card_url="")
    b = _company(id="c2", name="Окна Ростов", phone="", address="", card_url="")
    assert compare(a, b).kind == MATCH_NONE


def test_same_id_is_exact():
    a = _company()
    b = _company(id="c1", name="Другое название")
    assert compare(a, b).is_exact


def test_merge_fills_empty_fields_from_duplicate():
    primary = _company(id="primary", address=None, phone=None)
    secondary = _company(id="secondary", phone="+7 999 000-00-00", address="ул. Пушкина 10")
    merged = merge_companies(primary, secondary)

    assert merged.phone == "+7 999 000-00-00"
    assert merged.address == "ул. Пушкина 10"
    assert merged.id == "primary"


def test_merge_keeps_non_empty_primary():
    primary = _company(id="primary", address="ул. Ленина 1")
    secondary = _company(id="secondary", address="ул. Пушкина 10")
    merged = merge_companies(primary, secondary)
    assert merged.address == "ул. Ленина 1"


def test_merge_chooses_higher_reviews_count():
    primary = _company(id="primary", reviews_count=10)
    secondary = _company(id="secondary", reviews_count=45)
    merged = merge_companies(primary, secondary)
    assert merged.reviews_count == 45


def test_merge_records_all_sources():
    primary = _company(id="primary", source_name="2ГИС")
    secondary = _company(id="secondary", source_name="Яндекс Карты")
    merged = merge_companies(primary, secondary)
    assert "2ГИС" in merged.source_name
    assert "Яндекс Карты" in merged.source_name


def test_merge_earliest_first_seen_wins():
    primary = _company(id="primary", first_seen="2026-10-25")
    secondary = _company(id="secondary", first_seen="2026-10-01")
    merged = merge_companies(primary, secondary)
    assert merged.first_seen == "2026-10-01"


def test_merge_best_website_status_priority():
    primary = _company(id="primary", website_status="NOT_CHECKED")
    secondary = _company(id="secondary", website_status="NO_WEBSITE_CONFIRMED")
    merged = merge_companies(primary, secondary)
    assert merged.website_status == "NO_WEBSITE_CONFIRMED"


def test_find_matches_puts_exact_first():
    candidate = _company(id="cand")
    exact = _company(id="exact", phone="+7 863 111-22-33")
    doubtful = _company(id="doubtful", phone="", card_url="", address="")
    existing = [doubtful, exact]

    matches = find_matches(candidate, existing)
    assert len(matches) == 2
    assert matches[0][1].is_exact
    assert matches[0][0].id == "exact"

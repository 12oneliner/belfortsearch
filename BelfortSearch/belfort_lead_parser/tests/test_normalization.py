"""Тесты нормализации (ТЗ п.19, пункт 6)."""

from utils.normalization import (
    normalize_company_name,
    normalize_phone,
    normalize_text,
    normalize_url,
)


def test_normalize_text_removes_punctuation_and_case():
    assert normalize_text('  ООО "Потолки-Юг"! ') == "ооо потолки юг"


def test_normalize_text_handles_none_and_empty():
    assert normalize_text(None) == ""
    assert normalize_text("") == ""


def test_normalize_company_name_equal_for_variants():
    assert normalize_company_name('ООО «Ремонт+»') == normalize_company_name("ооо ремонт +")


def test_normalize_phone_converts_leading_eight():
    assert normalize_phone("8 (863) 123-45-67") == "78631234567"


def test_normalize_phone_keeps_plus_seven_digits():
    assert normalize_phone("+7 863 123 45 67") == "78631234567"


def test_normalize_phone_handles_missing():
    assert normalize_phone(None) == ""


def test_normalize_url_strips_slash_and_case():
    assert normalize_url("HTTPS://Example.RU/") == "https://example.ru"

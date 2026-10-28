"""Тесты поиска контактов (ТЗ п.8, п.19: пункт 8)."""

from core.contact_finder import CONF_HIGH, CONF_MEDIUM, CONF_LOW, ContactFinder, extract_emails, extract_phones, extract_telegrams, detect_role
from database.models import Company


def _company(**overrides) -> Company:
    data = dict(id="c1", name="Потолки Юг", niche="натяжные потолки",
                city="Ростов-на-Дону", phone="+7 863 111-22-33")
    data.update(overrides)
    return Company(**data)


def test_extract_phones_normalizes_and_dedups():
    text = "Звоните +7 (863) 111-22-33 или 8-863-111-22-33 (тот же номер)"
    assert extract_phones(text) == ["78631112233"]


def test_extract_telegrams():
    text = "Связь: https://t.me/potolki_yug и t.me/potolki_yug"
    assert extract_telegrams(text) == ["potolki_yug"]


def test_extract_emails_case_insensitive():
    text = "Почта: Info@Example.RU, info@example.ru"
    assert extract_emails(text) == ["info@example.ru"]


def test_contact_from_card_phone_only():
    finder = ContactFinder(fetch_fn=lambda url: None)
    company = _company(phone="+7 863 111-22-33")
    results = finder.find(company)
    assert any(r.contact.contact_type == "phone" and r.contact.confidence == CONF_HIGH for r in results)


def test_page_contacts_extracted():
    html = ("<html>Телефон: +7 999 000-11-22. Пишите в "
            "https://t.me/ivan_petrov. Почта: ivan@example.ru</html>")
    finder = ContactFinder(fetch_fn=lambda url: html)
    company = _company(phone="", website_url="https://potolki-yug.ru")
    results = finder.find(company)
    values = {r.contact.value for r in results}
    assert "79990001122" in values
    assert "ivan_petrov" in [v.split("/")[-1] for v in values]
    assert "ivan@example.ru" in values


def test_no_contacts_without_data():
    finder = ContactFinder(fetch_fn=lambda url: None)
    company = _company(phone="", website_url=None)
    assert finder.find(company) == []


def test_unavailable_page_is_skipped():
    def fetch(url):
        raise ConnectionError("нет сети")
    finder = ContactFinder(fetch_fn=fetch)
    company = _company(phone="+7 863 111-22-33", website_url="https://example.ru")
    results = finder.find(company)
    phones = [r.contact.value for r in results if r.contact.contact_type == "phone"]
    assert "78631112233" in phones


def test_name_without_role_is_low_confidence_only():
    """Имя человека без маркера роли — не контакт владельца (ТЗ п.8)."""
    role, confidence = detect_role("звоните Ивану, он отвечает")
    assert role is None
    assert confidence == CONF_LOW


def test_role_marker_detected():
    role, confidence = detect_role("генеральный директор Иванов Петр")
    assert role == "генеральный директор"
    assert confidence == CONF_MEDIUM

"""Тесты системы оценки (ТЗ п.19: пункты 1-3)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from core.scoring import (
    MIN_RATING,
    W_ACTIVITY,
    W_CONTACTS,
    W_FRESHNESS,
    W_NO_WEBSITE,
    W_OWNER,
    W_PHOTOS,
    W_RATING,
    W_SOCIAL,
    score_company,
)
from database.models import (
    WEBSITE_CHECK_FAILED,
    WEBSITE_FOUND,
    WEBSITE_NO_WEBSITE_CONFIRMED,
    WEBSITE_NOT_CHECKED,
    WEBSITE_UNCERTAIN,
    Company,
    Contact,
)

NOW = datetime(2026, 10, 27, tzinfo=timezone.utc)


def _company(**overrides) -> Company:
    data = dict(id="c1", name="Потолки Юг", niche="натяжные потолки", city="Ростов-на-Дону")
    data.update(overrides)
    return Company(**data)


def test_weights_sum_to_exactly_100():
    assert (
        W_NO_WEBSITE + W_ACTIVITY + W_RATING + W_FRESHNESS
        + W_PHOTOS + W_SOCIAL + W_OWNER + W_CONTACTS
    ) == 100


def test_perfect_company_scores_100():
    company = _company(
        website_status=WEBSITE_NO_WEBSITE_CONFIRMED,
        reviews_count=50,
        rating=4.9,
        last_review_date=(NOW - timedelta(days=30)).isoformat(),
        has_work_photos=1,
        social_activity="active",
        phone="+7 863 111-22-33",
        address="ул. Ленина, 1",
    )
    contacts = [
        Contact(id="k1", company_id="c1", contact_type="person", value="Иван Петров",
                role="директор", source="сайт", confidence="high")
    ]
    result = score_company(company, contacts, now=NOW)
    assert result.total == 100
    assert "ИТОГО: 100/100" in result.explanation


def test_empty_company_scores_zero_without_penalty_claims():
    result = score_company(_company(), now=NOW)
    assert result.total == 0
    assert result.reject_by_rating is False
    # Отсутствие данных не должно подаваться как подтверждённое отсутствие признака.
    assert "не проверено" in result.explanation


def test_missing_data_differs_from_confirmed_absence():
    not_checked = score_company(_company(has_work_photos=None), now=NOW)
    confirmed_absent = score_company(_company(has_work_photos=0), now=NOW)
    photos_not_checked = [i for i in not_checked.items if i.category == "Фото работ"][0]
    photos_absent = [i for i in confirmed_absent.items if i.category == "Фото работ"][0]

    assert photos_not_checked.points == photos_absent.points == 0
    assert "не проверено" in photos_not_checked.reason
    assert "подтверждено" in photos_absent.reason


def test_rating_below_minimum_marks_rejection():
    result = score_company(_company(rating=3.7), now=NOW)
    assert result.reject_by_rating is True
    rating_item = [i for i in result.items if i.category == "Рейтинг"][0]
    assert rating_item.points == 0


def test_rating_at_minimum_is_not_rejected():
    result = score_company(_company(rating=MIN_RATING), now=NOW)
    assert result.reject_by_rating is False
    rating_item = [i for i in result.items if i.category == "Рейтинг"][0]
    assert rating_item.points > 0


def test_unknown_rating_is_not_rejection():
    result = score_company(_company(rating=None), now=NOW)
    assert result.reject_by_rating is False


def test_website_found_gives_no_points_and_excludes():
    result = score_company(_company(website_status=WEBSITE_FOUND), now=NOW)
    assert result.excluded_by_website is True
    item = [i for i in result.items if i.category == "Без сайта"][0]
    assert item.points == 0


def test_confirmed_no_website_gives_full_points():
    result = score_company(_company(website_status=WEBSITE_NO_WEBSITE_CONFIRMED), now=NOW)
    item = [i for i in result.items if i.category == "Без сайта"][0]
    assert item.points == W_NO_WEBSITE
    assert result.excluded_by_website is False


def test_uncertain_and_failed_statuses_give_zero_but_not_excluded():
    for status in (WEBSITE_UNCERTAIN, WEBSITE_CHECK_FAILED, WEBSITE_NOT_CHECKED):
        result = score_company(_company(website_status=status), now=NOW)
        item = [i for i in result.items if i.category == "Без сайта"][0]
        assert item.points == 0
        assert result.excluded_by_website is False


def test_review_freshness_tiers():
    fresh = score_company(
        _company(last_review_date=(NOW - timedelta(days=60)).isoformat()), now=NOW
    )
    medium = score_company(
        _company(last_review_date=(NOW - timedelta(days=300)).isoformat()), now=NOW
    )
    old = score_company(
        _company(last_review_date=(NOW - timedelta(days=800)).isoformat()), now=NOW
    )

    def freshness(result):
        return [i for i in result.items if i.category == "Свежесть"][0].points

    assert freshness(fresh) == W_FRESHNESS
    assert freshness(medium) == 6
    assert freshness(old) == 2


def test_invalid_review_date_treated_as_unknown():
    result = score_company(_company(last_review_date="не дата"), now=NOW)
    item = [i for i in result.items if i.category == "Свежесть"][0]
    assert item.points == 0
    assert "неизвестна" in item.reason


def test_owner_contact_confidence_levels():
    def owner_points(confidence):
        contacts = [
            Contact(id="k", company_id="c1", contact_type="person", value="Иван",
                    role="директор", source="сайт", confidence=confidence)
        ]
        result = score_company(_company(), contacts, now=NOW)
        return [i for i in result.items if i.category == "Владелец"][0].points

    assert owner_points("high") == W_OWNER
    assert owner_points("medium") == 6
    assert owner_points("low") == 3


def test_person_name_without_role_still_requires_confidence():
    """Имя без подтверждения роли не даёт полный балл (ТЗ п.8)."""
    contacts = [
        Contact(id="k", company_id="c1", contact_type="person", value="Иван",
                role=None, source="страница", confidence="low")
    ]
    result = score_company(_company(), contacts, now=NOW)
    assert [i for i in result.items if i.category == "Владелец"][0].points == 3


def test_company_phone_only_still_scores_as_lead():
    """Руководитель не найден, но телефон компании есть (ТЗ п.8)."""
    result = score_company(_company(phone="+7 863 111-22-33"), now=NOW)
    contacts_item = [i for i in result.items if i.category == "Контакты"][0]
    owner_item = [i for i in result.items if i.category == "Владелец"][0]
    assert contacts_item.points == 3
    assert owner_item.points == 0
    assert result.total > 0


def test_contact_completeness_phone_and_address():
    result = score_company(_company(phone="+79990001122", address="ул. Мира 5"), now=NOW)
    assert [i for i in result.items if i.category == "Контакты"][0].points == W_CONTACTS


def test_zero_reviews_is_not_treated_as_closed_company():
    result = score_company(_company(reviews_count=0), now=NOW)
    item = [i for i in result.items if i.category == "Активность"][0]
    assert item.points == 0
    assert "не признак закрытия" in item.reason


def test_activity_tiers_by_reviews_count():
    def activity(count):
        result = score_company(_company(reviews_count=count), now=NOW)
        return [i for i in result.items if i.category == "Активность"][0].points

    assert activity(50) == W_ACTIVITY
    assert activity(20) == 15
    assert activity(7) == 10
    assert activity(2) == 5


def test_social_activity_levels():
    def social(value):
        result = score_company(_company(social_activity=value), now=NOW)
        return [i for i in result.items if i.category == "Соцсети"][0].points

    assert social("active") == W_SOCIAL
    assert social("есть") == 3
    assert social("нет") == 0
    assert social(None) == 0


def test_rating_tiers():
    def rating_points(value):
        result = score_company(_company(rating=value), now=NOW)
        return [i for i in result.items if i.category == "Рейтинг"][0].points

    assert rating_points(4.9) == W_RATING
    assert rating_points(4.6) == 12
    assert rating_points(4.3) == 9
    assert rating_points(4.0) == 6


def test_explanation_lists_every_category():
    result = score_company(_company(), now=NOW)
    for category in ("Без сайта", "Активность", "Рейтинг", "Свежесть",
                     "Фото работ", "Соцсети", "Владелец", "Контакты"):
        assert category in result.explanation


def test_score_recalculation_changes_total():
    """Пересчёт при изменении данных (ТЗ п.11)."""
    before = score_company(_company(), now=NOW).total
    after = score_company(
        _company(website_status=WEBSITE_NO_WEBSITE_CONFIRMED), now=NOW
    ).total
    assert after == before + W_NO_WEBSITE

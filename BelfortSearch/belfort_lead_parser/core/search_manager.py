"""Оркестратор поиска: источники → дедупликация → проверка сайтов → контакты → скоринг → сохранение (ТЗ п.16)."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Callable

from core.contact_finder import ContactFinder
from core.deduplication import find_matches, merge_companies
from core.scoring import score_company
from core.website_checker import (
    WEBSITE_FOUND,
    WEBSITE_NO_WEBSITE_CONFIRMED,
    WebsiteChecker,
)
from database.connection import init_db
from database.models import Company, Run, WebsiteCheck
from database.repository import (
    CompanyRepository,
    ContactRepository,
    RunRepository,
    WebsiteCheckRepository,
)
from sources.base import BaseSource, RawCompany
from sources.web_search import duckduckgo_search
from utils.logging_config import setup_logging
from utils.normalization import normalize_company_name, normalize_phone

logger = setup_logging()


class SearchManager:
    """Один запуск поиска под управлением пользователя."""

    def __init__(
        self,
        db_path=None,
        website_checker: WebsiteChecker | None = None,
        contact_finder: ContactFinder | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> None:
        self.conn = init_db(db_path)
        self.companies = CompanyRepository(self.conn)
        self.contacts = ContactRepository(self.conn)
        self.website_checks = WebsiteCheckRepository(self.conn)
        self.runs = RunRepository(self.conn)
        # По умолчанию реальная проверка через веб-поиск: без неё отсутствие
        # сайта не подтверждается и все компании уходят в «сомнительные».
        self.website_checker = website_checker or WebsiteChecker(
            search_fn=duckduckgo_search
        )
        self.contact_finder = contact_finder or ContactFinder()
        self.cancel_check = cancel_check or (lambda: False)

        self.counters: dict[str, int] = {
            "found": 0,
            "processed": 0,
            "unique": 0,
            "checked_websites": 0,
            "confirmed_no_website": 0,
            "quality_leads": 0,
            "rejected": 0,
            "doubtful": 0,
        }

    def close(self) -> None:
        self.conn.close()

    def run(
        self,
        niche: str,
        city: str,
        sources: list[BaseSource],
        target_leads: int = 50,
        limit_per_source: int = 100,
    ) -> dict:
        """Выполняет поиск по всем источникам, возвращает итоговую сводку."""
        run = self.runs.start(
            Run(
                id="",
                niche=niche,
                city=city,
                sources=json.dumps([s.name for s in sources]),
                target_leads=target_leads,
            )
        )
        run_id = run.id

        existing = self.companies.list_all()

        for source in sources:
            if self.cancel_check():
                break
            if not source.is_available():
                self.runs.add_error(run_id, source.name, "Источник недоступен")
                continue
            try:
                raw_items, status = source.search(niche, city, limit_per_source)
            except Exception as exc:  # не маскируем: логируем и продолжаем с другими источниками
                logger.exception("Ошибка источника %s", source.name)
                self.runs.add_error(run_id, source.name, str(exc))
                continue
            for err in status.errors:
                self.runs.add_error(run_id, source.name, err)

            for raw in raw_items:
                if self.cancel_check():
                    break
                self.counters["found"] += 1
                self._process_raw(raw, run_id, existing, niche, city)
                self.counters["processed"] += 1

                if self.counters["quality_leads"] >= target_leads:
                    logger.info(
                        "Достигнуто целевое количество лидов: %s", target_leads
                    )
                    break

        stats = dict(self.counters)
        stats["run_id"] = run_id
        started = run.started_at
        if started:
            stats["duration_seconds"] = (
                datetime.now(timezone.utc) - datetime.fromisoformat(started)
            ).total_seconds()

        self.runs.finish(
            run_id,
            found=stats["found"],
            unique_count=stats["unique"],
            checked_websites=stats["checked_websites"],
            confirmed_no_website=stats["confirmed_no_website"],
            quality_leads=stats["quality_leads"],
            rejected=stats["rejected"],
            doubtful=stats["doubtful"],
        )
        return stats

    def _process_raw(
        self, raw: RawCompany, run_id: str, existing: list[Company], niche: str, city: str
    ) -> Company | None:
        """Обрабатывает одну запись из источника: дедуп, сайт, контакты, скоринг.

        Возвращает обработанную компанию (или None при остановке).
        """
        company = Company(
            id="",
            name=raw.name or "",
            niche=raw.niche or niche,
            city=raw.city or city,
            address=raw.address,
            phone=raw.phone,
            normalized_phone=normalize_phone(raw.phone),
            normalized_name=normalize_company_name(raw.name),
            card_url=raw.card_url,
            website_url=raw.website_url,
            source_name=raw.source_name,
            rating=raw.rating,
            reviews_count=raw.reviews_count,
        )

        # Дедупликация против уже известных записей.
        matches = find_matches(company, existing)
        exact_match = next((m for m in matches if m[1].is_exact), None)
        doubtful_match = next((m for m in matches if m[1].is_doubtful), None)

        if exact_match is not None:
            other, result = exact_match
            merged = merge_companies(other, company)
            updates = {k: v for k, v in merged.__dict__.items() if k != "id"}
            self.companies.update(other.id, **updates)
            self.companies.update(other.id, processing_status="duplicate")
            return None

        if doubtful_match is not None:
            self.companies.add(company)
            existing.append(company)
            self.counters["unique"] += 1
            self.counters["doubtful"] += 1
            self.companies.update(company.id, processing_status="doubtful")
            return company

        # Новая компания.
        self.companies.add(company)
        existing.append(company)
        self.counters["unique"] += 1

        # Проверка сайта.
        check_result = self.website_checker.check(company)
        self.website_checks.add(
            WebsiteCheck(
                id="",
                company_id=company.id,
                status=check_result.status,
                evidence="\n".join(check_result.evidence),
            )
        )
        self.companies.update(company.id, website_status=check_result.status)
        company.website_status = check_result.status
        self.counters["checked_websites"] += 1

        if check_result.status == WEBSITE_NO_WEBSITE_CONFIRMED:
            self.counters["confirmed_no_website"] += 1

        # Публичные контакты.
        contacts = self.contact_finder.find(company)
        for evidence in contacts:
            contact = evidence.contact
            contact.company_id = company.id
            self.contacts.add(contact)

        # Оценка.
        stored_contacts = self.contacts.list_for_company(company.id)
        scoring = score_company(company, stored_contacts)
        processing_status = (
            "rejected"
            if scoring.reject_by_rating or company.website_status == WEBSITE_FOUND
            else "fit"
        )
        self.companies.update(
            company.id,
            score=scoring.total,
            score_explanation=scoring.explanation,
            processing_status=processing_status,
        )

        if scoring.reject_by_rating or company.website_status == WEBSITE_FOUND:
            self.counters["rejected"] += 1
        elif company.website_status == WEBSITE_NO_WEBSITE_CONFIRMED:
            self.counters["quality_leads"] += 1
        else:
            # UNCERTAIN — отдельный список для повторной проверки.
            self.counters["doubtful"] += 1

        return company

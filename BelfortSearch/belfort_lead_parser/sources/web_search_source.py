"""Веб-поиск как источник компаний (ТЗ п.5).

Работает без API-ключей: берёт выдачу обычного поискового запроса
(«натяжные потолки Москва»), отбрасывает каталоги, маркетплейсы и соцсети
и оставляет сайты, похожие на сайты самих компаний.

Честные ограничения источника:
- выдача не содержит телефонов, адресов, рейтингов и числа отзывов —
  эти поля остаются пустыми (None), приложение их не выдумывает;
- название компании берётся из заголовка результата и может быть
  неточным (маркетинговый заголовок вместо юридического названия);
- в выдачу попадают не все компании города, а только те, чьи сайты
  поисковик показал по этим запросам.

Поисковый движок инжектируется (search_fn), поэтому тесты идут офлайн.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Callable
from urllib.parse import urlparse

from core.website_checker import SITE_KIND_BUILDER, SITE_KIND_OWN, classify_url
from sources.base import BaseSource, RawCompany, SourceStatus
from utils.normalization import normalize_text

SOURCE_NAME = "web_search"

# Шаблоны запросов: ниша + город в разных формулировках.
# Разные формулировки дают разные срезы выдачи, поэтому компаний находится
# больше, чем по одному запросу.
QUERY_TEMPLATES = (
    "{niche} {city}",
    "{niche} {city} заказать",
    "{niche} {city} цены",
    "{niche} в {city} компания",
    "{niche} {city} контакты",
)

# Разделители в заголовках результатов: "Потолки Люкс — натяжные потолки".
_TITLE_SPLIT_RE = re.compile(r"\s*[—–\-|•·:]{1,2}\s*|\s{2,}")

# Маркетинговые слова: сегмент заголовка, состоящий только из них (плюс ниша
# и город), названием компании не является.
_GENERIC_TITLE_WORDS = {
    "официальный", "сайт", "оффициальный", "главная", "home",
    "купить", "заказать", "цены", "цена", "недорого", "дешево", "дёшево",
    "под", "ключ", "от", "производителя", "с", "гарантией", "гарантия",
    "установка", "монтаж", "замер", "бесплатно", "акции", "скидки",
    "в", "на", "и", "для", "по", "компания", "фирма", "москве", "москва",
    "стоимость", "каталог", "услуги", "работы", "быстро", "качественно",
    "лучшие", "топ", "рейтинг", "отзывы", "фото", "портфолио", "прайс",
}

# Домены-агрегаторы и справочники сверх списка website_checker: там, где
# собирается множество разных компаний, конкретного лида нет.
EXTRA_AGGREGATOR_DOMAINS = {
    "uslugi.yandex.ru", "yandex.ru", "market.yandex.ru",
    "profi.ru", "youdo.com", "remontnik.ru", "pulscen.ru",
    "tiu.ru", "satom.ru", "blizko.ru", "regmarkets.ru",
    "spr.ru", "orgpage.ru", "rusprofile.ru", "list-org.ru",
    "zoon.ru", "yell.ru", "flamp.ru", "otzovik.com", "irecommend.ru",
    "wikipedia.org", "dzen.ru", "pikabu.ru", "habr.com",
    "youtube.com", "vk.com", "ok.ru", "t.me",
    "avito.ru", "yula.ru", "ozon.ru", "wildberries.ru",
    "sravni.ru", "banki.ru", "2gis.ru", "google.com",
}

SearchFn = Callable[[str, int], list[dict]]


def _host(url: str | None) -> str:
    """Домен URL без www. Пустая строка, если URL разобрать не удалось."""
    if not url:
        return ""
    text = url.strip()
    if "://" not in text:
        text = "https://" + text
    try:
        host = urlparse(text).netloc.casefold()
    except ValueError:
        return ""
    if host.startswith("www."):
        host = host[4:]
    return host.split(":")[0]


def _is_aggregator(url: str | None) -> bool:
    """True, если домен — агрегатор, справочник, соцсеть или маркетплейс."""
    host = _host(url)
    if not host:
        return True
    for domain in EXTRA_AGGREGATOR_DOMAINS:
        if host == domain or host.endswith("." + domain):
            return True
    return classify_url(url) not in (SITE_KIND_OWN, SITE_KIND_BUILDER)


def _is_generic_segment(segment: str, niche: str, city: str) -> bool:
    """True, если сегмент заголовка — маркетинговый текст, а не название.

    Сегмент считается общим, если каждое его слово входит в стоп-список,
    в название ниши или в название города.
    """
    words = normalize_text(segment).split()
    if not words:
        return True
    niche_words = set(normalize_text(niche).split())
    city_words = set(normalize_text(city).split())
    allowed = _GENERIC_TITLE_WORDS | niche_words | city_words
    return all(word in allowed for word in words)


def extract_company_name(title: str | None, niche: str, city: str) -> str | None:
    """Выделяет название компании из заголовка результата поиска.

    Заголовок режется по тире/вертикальной черте, затем берётся первый
    сегмент, который не является чистой маркетинговой фразой. Если все
    сегменты общие — возвращается None: компании в этом результате нет.
    """
    if not title or not title.strip():
        return None
    segments = [s.strip(" .,;:!\"'«»()") for s in _TITLE_SPLIT_RE.split(title)]
    segments = [s for s in segments if s]
    for segment in segments:
        if len(segment) < 3 or len(segment) > 120:
            continue
        if _is_generic_segment(segment, niche, city):
            continue
        return segment
    return None


class WebSearchSource(BaseSource):
    """Источник компаний из обычного веб-поиска.

    На каждый запрос генерирует несколько формулировок (QUERY_TEMPLATES),
    ходит по ним последовательно (с паузой RateLimiter) и отсеивает всё,
    кроме сайтов, похожих на сайты компаний.
    """

    name = SOURCE_NAME

    def __init__(
        self,
        search_fn: SearchFn | None = None,
        fetch_phones: bool = False,
    ) -> None:
        self.search_fn = search_fn
        # По умолчанию False: не ходим по чужим сайтам без нужды, не замедляем
        # поиск. Телефоны потом доберёт ContactFinder для компаний с сайтом.
        self.fetch_phones = fetch_phones

    def is_available(self) -> bool:
        # Источник всегда доступен: он не нуждается в ключе, только в сети.
        return True

    def _search(self, query: str, limit: int) -> list[dict]:
        fn = self.search_fn
        if fn is None:
            from sources.web_search import duckduckgo_search

            def _default(q: str, _max: int) -> list[dict]:
                return duckduckgo_search(q, max_results=_max)

            fn = _default
        try:
            return fn(query, limit) or []
        except Exception:  # сеть упала — не ломаем весь запуск
            return []

    def _page_phone(self, url: str) -> str | None:
        """Пытается найти телефон на странице компании (для таблицы лидов).

        Возвращает первый найденный телефон или None. Ошибки сети
        не ломают обработку: пустое поле — не признак отсутствия телефона.
        """
        from core.contact_finder import extract_phones
        from utils.http_client import HttpClient

        try:
            response = HttpClient().get(url)
        except Exception:
            return None
        if response is None or not response.text:
            return None
        phones = extract_phones(response.text)
        return phones[0] if phones else None

    def search(self, niche: str, city: str, limit: int) -> tuple[list[RawCompany], SourceStatus]:
        """Ищет компании веб-поиском.

        Направляет несколько запросов подряд; из каждой страницы выдачи
        берёт первые several результатов-сайтов. Название берется из
        заголовка результата, URL — адрес сайта компании.
        """
        status = SourceStatus(
            source_name=self.name,
            started_at=datetime.now(timezone.utc),
        )
        seen_hosts: set[str] = set()
        results: list[RawCompany] = []

        for template in QUERY_TEMPLATES:
            if limit and len(results) >= limit:
                break
            query = template.format(niche=niche, city=city)
            try:
                hits = self._search(query, max(limit, 10))
            except Exception:  # источник недоступен — пропускаем шаблон
                status.limitations.append(f"Запрос «{query}» не выполнен (сеть)")
                continue

            status.found += len(hits)
            for hit in hits:
                if limit and len(results) >= limit:
                    break
                url = hit.get("url") or ""
                title = hit.get("title") or ""
                host = _host(url)
                if not host or host in seen_hosts or _is_aggregator(url):
                    continue

                name = extract_company_name(title, niche, city)
                if not name:
                    continue

                seen_hosts.add(host)
                phone = self._page_phone(url) if self.fetch_phones else None
                results.append(
                    RawCompany(
                        source_name=self.name,
                        name=name,
                        city=city,
                        niche=niche,
                        address=None,
                        phone=phone,
                        website_url=url,
                        card_url=None,
                        rating=None,
                        reviews_count=None,
                    )
                )
                status.processed += 1

        status.limitations.append(
            "Веб-поиск не возвращает телефоны, адреса и рейтинги компаний: "
            "эти поля остаются пустыми, показываются только найденные сайты."
        )
        status.finished_at = datetime.now(timezone.utc)
        return results, status

"""Проверка наличия сайта у компании (ТЗ п.9).

Пять статусов: NO_WEBSITE_CONFIRMED, WEBSITE_FOUND, UNCERTAIN, NOT_CHECKED,
CHECK_FAILED. Статус отсутствия сайта присваивается только по правилам,
учитывающим несколько независимых проверок. Отсутствие результатов поиска
не считается абсолютным доказательством.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable
from urllib.parse import urlparse

from database.models import (
    WEBSITE_CHECK_FAILED,
    WEBSITE_FOUND,
    WEBSITE_NO_WEBSITE_CONFIRMED,
    WEBSITE_NOT_CHECKED,
    WEBSITE_UNCERTAIN,
    Company,
)
from utils.normalization import normalize_company_name, normalize_text

# Домены, которые НЕ являются собственным сайтом компании.
CATALOG_DOMAINS = {
    "2gis.ru", "2gis.com",
    "yandex.ru", "yandex.com", "yandex.by", "yandex.kz",
    "maps.google.com", "google.com",
    "avito.ru", "yell.ru", "zoon.ru", "yelp.com", "tripadvisor.com",
    "flamp.ru", "irecommend.ru", "otzovik.com", "profi.ru", "youdo.com",
    "biglion.ru", "coupon.ru",
    "wildberries.ru", "ozon.ru", "market.yandex.ru", "sbermegamarket.ru",
}

SOCIAL_DOMAINS = {
    "vk.com", "ok.ru", "t.me", "telegram.me",
    "instagram.com", "facebook.com", "fb.com",
    "youtube.com", "tiktok.com", "dzen.ru", "rutube.ru",
    "whatsapp.com", "wa.me", "viber.com",
}

# Конструкторы: это собственный сайт компании, но другого вида.
BUILDER_DOMAINS = {
    "tilda.ws", "tilbash.page", "tildacdn.com",
    "wixsite.com", "wix.com",
    "ucoz.ru", "ucoz.com", "jimdofree.com", "jimdo.com",
    "nethouse.ru", "umi.ru", "lpmotor.ru", "lp-site.ru", "flexbe.com",
}

SITE_KIND_OWN = "own"          # собственный сайт (домен/визитка/корпоративный)
SITE_KIND_BUILDER = "builder"  # собственный сайт на конструкторе
SITE_KIND_CATALOG = "catalog"  # карточка каталога/маркетплейса — не сайт
SITE_KIND_SOCIAL = "social"    # соцсеть — не собственный сайт
SITE_KIND_UNKNOWN = "unknown"


def _domain(url: str | None) -> str:
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
    return host


def _domain_matches(host: str, domain: str) -> bool:
    return host == domain or host.endswith("." + domain)


def classify_url(url: str | None) -> str:
    """Определяет вид URL: собственный сайт, конструктор, каталог, соцсеть."""
    host = _domain(url)
    if not host:
        return SITE_KIND_UNKNOWN
    for domain in SOCIAL_DOMAINS:
        if _domain_matches(host, domain):
            return SITE_KIND_SOCIAL
    for domain in CATALOG_DOMAINS:
        if _domain_matches(host, domain):
            return SITE_KIND_CATALOG
    for domain in BUILDER_DOMAINS:
        if _domain_matches(host, domain):
            return SITE_KIND_BUILDER
    return SITE_KIND_OWN


def is_own_website(url: str | None) -> bool:
    """True только для собственного сайта (включая конструкторы)."""
    return classify_url(url) in (SITE_KIND_OWN, SITE_KIND_BUILDER)


_TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "c", "ч": "ch", "ш": "sh", "щ": "sch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}


def transliterate(text: str) -> str:
    """Транслитерирует кириллицу в латиницу для сравнения с доменами."""
    return "".join(_TRANSLIT.get(ch, ch) for ch in text.casefold())


def _significant_tokens(name: str | None) -> list[str]:
    tokens = normalize_company_name(name).split()
    stop = {"ооо", "ип", "ао", "пао", "зао", "оао", "компания", "группа", "студия"}
    return [t for t in tokens if len(t) >= 3 and t not in stop]


def _token_stems(token: str) -> set[str]:
    """Токен и его варианты с убранными русскими падежными endings."""
    stems = {token}
    for ending in ("а", "я", "у", "ю", "о", "е", "и", "ы", "ом", "ем", "ах", "ях", "ов", "ев"):
        if len(token) > len(ending) + 3 and token.endswith(ending):
            stems.add(token[: -len(ending)])
    return stems


def url_linked_to_company(url: str | None, title: str | None, company: Company) -> bool:
    """Проверяет, связан ли найденный URL с конкретной компанией.

    Связь подтверждается, если заголовок результата содержит название компании,
    или домен содержит как минимум два значимых токена названия (после
    транслитерации в латиницу и стемминга). Один общий токен (например,
    «ремонт» или «потолки») недостаточен: иначе чужой сайт с похожим словом
    в домене примут за сайт компании.
    """
    name_norm = normalize_company_name(company.name)
    title_norm = normalize_text(title)
    if name_norm and title_norm and name_norm in title_norm:
        return True
    host = _domain(url)
    if not host:
        return False
    host_flat = host.replace("-", "").replace(".", "")

    tokens = []
    for raw in _significant_tokens(company.name):
        token = transliterate(raw).replace("-", "")
        if len(token) >= 3:
            tokens.append(token)

    matched = 0
    for token in tokens:
        if any(stem and stem in host_flat for stem in _token_stems(token)):
            matched += 1

    if len(tokens) == 1:
        # Одно значимое слово (например «потолки» в «Потолки Юг») встречается
        # в доменах конкурентов (potolki-sever.ru), поэтому совпадения одного
        # токена в домене недостаточно. Связь признаём только если метка
        # домена равна самому токену (romashka.ru для «Ромашки»)
        # либо название есть в заголовке (проверено выше).
        label = host.split(".")[0].replace("-", "")
        return any(stem and stem == label for stem in _token_stems(tokens[0]))
    return matched >= 2


@dataclass
class WebsiteCheckResult:
    status: str = WEBSITE_NOT_CHECKED
    evidence: list[str] = field(default_factory=list)
    site_url: str | None = None
    site_kind: str = SITE_KIND_UNKNOWN


# Поисковые запросы для проверки (шаблоны; город и ниша подставляются).
SEARCH_QUERY_TEMPLATES = (
    "{name} {city}",
    "{name} {niche} {city}",
    "{name} официальный сайт",
)

# Минимум независимых проверок с данными для статуса NO_WEBSITE_CONFIRMED:
# карточка + не менее двух поисковых запросов, вернувших результаты.
MIN_SEARCHES_WITH_RESULTS = 2

SearchFn = Callable[[str], list[dict]]


class WebsiteChecker:
    """Проверяет наличие сайта. Поиск инжектится, чтобы тесты были офлайн."""

    def __init__(self, search_fn: SearchFn | None = None) -> None:
        self.search_fn = search_fn or (lambda query: [])

    def check(self, company: Company) -> WebsiteCheckResult:
        evidence: list[str] = []

        # Проверка 1: карточка источника.
        card_kind = classify_url(company.website_url)
        if company.website_url and is_own_website(company.website_url):
            evidence.append(
                f"Карточка: указан собственный сайт ({card_kind}): {company.website_url}"
            )
            return WebsiteCheckResult(
                status=WEBSITE_FOUND, evidence=evidence,
                site_url=company.website_url, site_kind=card_kind,
            )
        if company.website_url:
            evidence.append(
                f"Карточка: ссылка ведёт не на собственный сайт ({card_kind}): {company.website_url}"
            )
        else:
            evidence.append("Карточка: ссылка на сайт отсутствует")

        # Проверки 2+: поисковые запросы.
        queries = [t.format(name=company.name or "", niche=company.niche or "",
                            city=company.city or "") for t in SEARCH_QUERY_TEMPLATES]
        searches_with_results = 0
        failed = 0
        for query in queries:
            try:
                hits = self.search_fn(query) or []
            except Exception as exc:  # сеть недоступна — фиксируем, не маскируем
                failed += 1
                evidence.append(f"Поиск «{query}»: ошибка — {exc}")
                continue
            if not hits:
                evidence.append(f"Поиск «{query}»: результатов нет")
                continue
            searches_with_results += 1
            linked = [
                h for h in hits
                if url_linked_to_company(h.get("url"), h.get("title"), company)
                and is_own_website(h.get("url"))
            ]
            if linked:
                best = linked[0]
                kind = classify_url(best.get("url"))
                evidence.append(
                    f"Поиск «{query}»: найден собственный сайт ({kind}): {best.get('url')}"
                )
                return WebsiteCheckResult(
                    status=WEBSITE_FOUND, evidence=evidence,
                    site_url=best.get("url"), site_kind=kind,
                )
            catalog_only = all(
                classify_url(h.get("url")) in (SITE_KIND_CATALOG, SITE_KIND_SOCIAL, SITE_KIND_UNKNOWN)
                for h in hits
            )
            if catalog_only:
                evidence.append(
                    f"Поиск «{query}»: только каталоги/соцсети ({len(hits)} рез.), "
                    "собственного сайта нет"
                )
            else:
                evidence.append(
                    f"Поиск «{query}»: {len(hits)} рез., связь с компанией не подтверждена"
                )

        if failed == len(queries):
            evidence.append("Все поисковые проверки завершились ошибкой")
            return WebsiteCheckResult(status=WEBSITE_CHECK_FAILED, evidence=evidence)

        if searches_with_results >= MIN_SEARCHES_WITH_RESULTS:
            evidence.append(
                f"Итог: карточка + {searches_with_results} поисковых проверки "
                "не нашли собственного сайта — отсутствие подтверждено"
            )
            return WebsiteCheckResult(status=WEBSITE_NO_WEBSITE_CONFIRMED, evidence=evidence)

        evidence.append(
            "Итог: данных недостаточно — отсутствие сайта не подтверждено, "
            "требуется повторная проверка"
        )
        return WebsiteCheckResult(status=WEBSITE_UNCERTAIN, evidence=evidence)

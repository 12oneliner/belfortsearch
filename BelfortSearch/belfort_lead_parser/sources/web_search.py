"""Веб-поиск через DuckDuckGo HTML (без API-ключей, ТЗ п.5).

Используется ТОЛЬКО как проверка наличия сайта у компаний из CSV,
а не как самостоятельный источник лидов. Уважаем лимиты:
последовательные запросы, пауза между ними, без обхода блокировок.
При 401/403/429 поднимается AccessDenied — WebsiteChecker фиксирует
это как ошибку проверки, а не маскирует.
"""

from __future__ import annotations

import logging
from urllib.parse import parse_qs, unquote, urlparse

from utils.http_client import AccessDenied, HttpClient

logger = logging.getLogger(__name__)

_search_client = HttpClient()


def _unwrap_duckduckgo_url(href: str | None) -> str | None:
    """Раскрывает обёртку //duckduckgo.com/l/?uddg=<url>. Возвращает прямой URL."""
    if not href:
        return None
    href = href.strip()
    if href.startswith("//"):
        href = "https:" + href
    try:
        parsed = urlparse(href)
    except ValueError:
        return href or None
    if "duckduckgo.com" in parsed.netloc and parsed.path.startswith("/l"):
        target = parse_qs(parsed.query).get("uddg", [None])[0]
        if target:
            return unquote(target)
        return None
    return href


def duckduckgo_search(query: str, max_results: int = 10) -> list[dict]:
    """Выполняет один поисковый запрос, возвращает [{url, title}].

    Ошибки сети возвращают пустой список (проверка фиксирует «результатов нет»),
    запрет доступа (AccessDenied) пробрасывается наружу — WebsiteChecker
    зафиксирует его как ошибку проверки по этому запросу.
    """
    import httpx  # локальный импорт: консистентно с HttpClient

    _search_client.limiter.wait()
    url = "https://html.duckduckgo.com/html/"
    try:
        response = httpx.post(
            url,
            data={"q": query},
            timeout=_search_client.limits.timeout_seconds,
            follow_redirects=True,
            headers={
                "User-Agent": "BelfortLeadParser/0.1 (+local research tool)",
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
    except Exception as exc:
        logger.warning("DuckDuckGo: запрос «%s» не удался: %s", query, exc)
        return []

    if response.status_code in (401, 403, 429, 451):
        raise AccessDenied(
            f"DuckDuckGo ограничил доступ: HTTP {response.status_code}"
        )
    if not 200 <= response.status_code < 300:
        logger.warning("DuckDuckGo: HTTP %s для «%s»", response.status_code, query)
        return []

    from bs4 import BeautifulSoup  # локальный импорт: парсер нужен только здесь

    soup = BeautifulSoup(response.text, "html.parser")
    results: list[dict] = []
    for anchor in soup.select("a.result__a"):
        direct = _unwrap_duckduckgo_url(anchor.get("href"))
        title = anchor.get_text(" ", strip=True)
        if direct and title:
            results.append({"url": direct, "title": title})
        if len(results) >= max_results:
            break
    return results

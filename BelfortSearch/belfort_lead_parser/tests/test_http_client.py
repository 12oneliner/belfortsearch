"""Тесты HTTP-клиента: тайм-ауты, лимиты, повторы, запрет доступа (ТЗ п.17, п.19 п.12)."""

import pytest

from config.settings import NetworkLimits
from utils.http_client import AccessDenied, HttpClient, HttpResponse, RateLimiter


def test_rate_limiter_waits_between_calls():
    """Лимитер выдерживает минимальную паузу (без реального ожидания)."""
    limiter = RateLimiter(min_delay_seconds=0.05)
    limiter.wait()  # первый вызов проходит сразу
    import time

    start = time.monotonic()
    limiter.wait()
    assert time.monotonic() - start >= 0.04


def test_successful_get_returns_response():
    def transport(url):
        return HttpResponse(200, "<html>ок</html>", url)

    client = HttpClient(NetworkLimits(min_delay_seconds=0), transport=transport)
    response = client.get("https://example.ru")
    assert response is not None
    assert response.ok
    assert "ок" in response.text


def test_access_denied_is_raised_and_not_retried():
    """403/429 — запрет доступа: не обходим и не повторяем (ТЗ п.5)."""
    calls = {"n": 0}

    def transport(url):
        calls["n"] += 1
        return HttpResponse(403, "", url)

    client = HttpClient(NetworkLimits(min_delay_seconds=0, max_retries=3), transport=transport)
    with pytest.raises(AccessDenied):
        client.get("https://example.ru")
    assert calls["n"] == 1


def test_rate_limit_429_is_access_denied():
    def transport(url):
        return HttpResponse(429, "", url)

    client = HttpClient(NetworkLimits(min_delay_seconds=0), transport=transport)
    with pytest.raises(AccessDenied):
        client.get("https://example.ru")


def test_temporary_network_error_is_retried_then_succeeds():
    calls = {"n": 0}

    def transport(url):
        calls["n"] += 1
        if calls["n"] < 3:
            raise ConnectionError("обрыв соединения")
        return HttpResponse(200, "готово", url)

    client = HttpClient(
        NetworkLimits(min_delay_seconds=0, max_retries=2), transport=transport,
        sleep_fn=lambda s: None,
    )
    response = client.get("https://example.ru")
    assert response is not None
    assert calls["n"] == 3


def test_persistent_network_error_returns_none():
    def transport(url):
        raise TimeoutError("тайм-аут")

    client = HttpClient(
        NetworkLimits(min_delay_seconds=0, max_retries=1), transport=transport,
        sleep_fn=lambda s: None,
    )
    assert client.get("https://example.ru") is None


def test_server_error_is_retried():
    calls = {"n": 0}

    def transport(url):
        calls["n"] += 1
        if calls["n"] == 1:
            return HttpResponse(503, "", url)
        return HttpResponse(200, "ок", url)

    client = HttpClient(
        NetworkLimits(min_delay_seconds=0, max_retries=2), transport=transport,
        sleep_fn=lambda s: None,
    )
    assert client.get("https://example.ru") is not None
    assert calls["n"] == 2


def test_client_error_404_is_not_retried():
    calls = {"n": 0}

    def transport(url):
        calls["n"] += 1
        return HttpResponse(404, "", url)

    client = HttpClient(
        NetworkLimits(min_delay_seconds=0, max_retries=3), transport=transport,
        sleep_fn=lambda s: None,
    )
    assert client.get("https://example.ru") is None
    assert calls["n"] == 1

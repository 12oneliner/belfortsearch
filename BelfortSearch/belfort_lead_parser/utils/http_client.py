"""HTTP-клиент с тайм-аутами, ограничением частоты и безопасными повторами (ТЗ п.17).

Агрессивная параллельность не используется: запросы идут последовательно
с минимальной паузой между ними. Повторы только для временных сетевых ошибок;
коды 403/429 считаются запретом доступа и повторам не подлежат.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from config.settings import NetworkLimits

logger = logging.getLogger(__name__)

USER_AGENT = "BelfortLeadParser/0.1 (+local research tool)"

# Коды, при которых доступ запрещён или ограничен — повторять нельзя.
ACCESS_DENIED_CODES = (401, 403, 429, 451)


class AccessDenied(RuntimeError):
    """Источник запретил доступ (401/403/429/451) — корректно завершаем работу."""


class RateLimiter:
    """Минимальная пауза между запросами к одному источнику."""

    def __init__(self, min_delay_seconds: float = 1.0) -> None:
        self.min_delay = min_delay_seconds
        self._last_call: float | None = None

    def wait(self) -> None:
        if self._last_call is not None:
            elapsed = time.monotonic() - self._last_call
            remaining = self.min_delay - elapsed
            if remaining > 0:
                time.sleep(remaining)
        self._last_call = time.monotonic()


@dataclass
class HttpResponse:
    status_code: int
    text: str
    url: str

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 300


class HttpClient:
    """Обёртка над httpx с лимитами. Транспорт инжектируется для тестов."""

    def __init__(
        self,
        limits: NetworkLimits | None = None,
        transport=None,
        sleep_fn=time.sleep,
    ) -> None:
        self.limits = limits or NetworkLimits()
        self.limiter = RateLimiter(self.limits.min_delay_seconds)
        self._transport = transport
        self._sleep = sleep_fn

    def _send(self, url: str) -> HttpResponse:
        if self._transport is not None:
            return self._transport(url)

        import httpx  # импорт внутри: тесты работают без сети и без httpx

        response = httpx.get(
            url,
            timeout=self.limits.timeout_seconds,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT},
        )
        return HttpResponse(response.status_code, response.text, str(response.url))

    def get(self, url: str) -> HttpResponse | None:
        """Запрашивает страницу. Возвращает None, если получить не удалось.

        AccessDenied поднимается при явном запрете доступа — его нельзя
        обходить, работа с источником прекращается.
        """
        attempts = self.limits.max_retries + 1
        last_error: Exception | None = None

        for attempt in range(1, attempts + 1):
            self.limiter.wait()
            try:
                response = self._send(url)
            except Exception as exc:  # временная сетевая ошибка
                last_error = exc
                logger.warning("Запрос %s не удался (попытка %s/%s): %s",
                               url, attempt, attempts, exc)
                if attempt < attempts:
                    self._sleep(self.limits.min_delay_seconds * attempt)
                continue

            if response.status_code in ACCESS_DENIED_CODES:
                raise AccessDenied(
                    f"Источник ограничил доступ: HTTP {response.status_code} для {url}"
                )
            if response.ok:
                return response

            logger.warning("HTTP %s для %s", response.status_code, url)
            if 500 <= response.status_code < 600 and attempt < attempts:
                self._sleep(self.limits.min_delay_seconds * attempt)
                continue
            return None

        if last_error is not None:
            logger.error("Запрос %s не выполнен после %s попыток", url, attempts)
        return None

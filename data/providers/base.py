from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from typing import Any

import requests

from data.models import (
    Fundamentals,
    History,
    MacroSeries,
    NewsItem,
    Quote,
    Statements,
    SymbolInfo,
)

log = logging.getLogger(__name__)


class ProviderError(RuntimeError):
    pass


class ProviderUnavailable(ProviderError):
    pass


class RateLimited(ProviderError):
    pass


class SymbolNotFound(ProviderError):
    pass


class ConfigError(ProviderError):
    pass


class HttpClient:
    def __init__(self, user_agent: str, timeout: float = 10.0, retries: int = 2):
        self.timeout = timeout
        self.retries = retries
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": user_agent})

    def get(self, url: str, params: dict[str, Any] | None = None, headers: dict[str, str] | None = None) -> requests.Response:
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                response = self.session.get(url, params=params, headers=headers, timeout=self.timeout)
            except requests.RequestException as exc:
                last_error = exc
                log.warning("request failed (%s) attempt %d: %s", url, attempt + 1, exc)
                time.sleep(min(0.5 * (2 ** attempt), 3.0))
                continue
            if response.status_code == 429:
                retry_after = response.headers.get("Retry-After")
                delay = min(float(retry_after) if retry_after and retry_after.isdigit() else 2.0 ** attempt, 10.0)
                last_error = RateLimited("rate limited by provider")
                time.sleep(delay)
                continue
            if response.status_code >= 500:
                last_error = ProviderUnavailable(f"provider server error {response.status_code}")
                time.sleep(min(0.5 * (2 ** attempt), 3.0))
                continue
            return response
        if isinstance(last_error, RateLimited):
            raise last_error
        raise ProviderUnavailable(f"request failed for {url}: {last_error}")

    def get_json(self, url: str, params: dict[str, Any] | None = None, headers: dict[str, str] | None = None) -> Any:
        response = self.get(url, params=params, headers=headers)
        if response.status_code >= 400:
            raise ProviderUnavailable(f"HTTP {response.status_code} from {url}")
        try:
            return response.json()
        except ValueError as exc:
            raise ProviderError(f"invalid JSON from {url}") from exc


class MarketDataProvider(ABC):
    name: str = "market"
    is_demo: bool = False

    @abstractmethod
    def search(self, query: str, limit: int = 8) -> list[SymbolInfo]: ...

    @abstractmethod
    def quote(self, symbol: str) -> Quote: ...

    @abstractmethod
    def history(self, symbol: str, period: str, interval: str | None = None) -> History: ...


class FundamentalDataProvider(ABC):
    name: str = "fundamentals"
    is_demo: bool = False

    @abstractmethod
    def snapshot(self, symbol: str) -> Fundamentals: ...

    @abstractmethod
    def statements(self, symbol: str, period: str = "annual") -> Statements: ...

    @abstractmethod
    def profile(self, symbol: str) -> SymbolInfo: ...


class NewsProvider(ABC):
    name: str = "news"
    is_demo: bool = False

    @abstractmethod
    def headlines(
        self,
        symbols: list[str] | None = None,
        query: str | None = None,
        limit: int = 50,
    ) -> list[NewsItem]: ...


class MacroDataProvider(ABC):
    name: str = "macro"
    is_demo: bool = False

    @abstractmethod
    def series(self, series_id: str, limit: int = 800) -> MacroSeries: ...

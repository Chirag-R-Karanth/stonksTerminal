from __future__ import annotations

import time
from typing import Any

from data.models import Candle, History, Quote, SymbolInfo
from data.providers.base import (
    HttpClient,
    MarketDataProvider,
    ProviderError,
    RateLimited,
    SymbolNotFound,
)
from database.sqlite_db import utcnow_iso


class AlphaVantageMarketProvider(MarketDataProvider):
    name = "alphavantage"

    def __init__(self, config: dict[str, Any]):
        self.base_url = str(config.get("base_url", "https://www.alphavantage.co/query")).rstrip("/")
        self.api_key = config.get("_api_key")
        network = config.get("_network", {})
        self.client = HttpClient(
            user_agent=str(network.get("user_agent", "personal-financial-terminal/0.1")),
            timeout=float(network.get("timeout_seconds", 10)),
            retries=int(network.get("retries", 1)),
        )

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def _require_key(self) -> None:
        if not self.api_key:
            from data.providers.base import ConfigError

            raise ConfigError("Alpha Vantage API key not configured (set ALPHA_VANTAGE_API_KEY)")

    def _call(self, params: dict[str, Any]) -> dict[str, Any]:
        self._require_key()
        merged = {**params, "apikey": self.api_key}
        data = self.client.get_json(self.base_url, params=merged)
        if isinstance(data, dict):
            if data.get("Note") or data.get("Information"):
                raise RateLimited(str(data.get("Note") or data.get("Information")))
            if data.get("Error Message"):
                raise SymbolNotFound(str(data["Error Message"]))
        return data

    def search(self, query: str, limit: int = 8) -> list[SymbolInfo]:
        data = self._call({"function": "SYMBOL_SEARCH", "keywords": query})
        out: list[SymbolInfo] = []
        for item in data.get("bestMatches", [])[:limit]:
            symbol = item.get("1. symbol")
            if not symbol:
                continue
            out.append(SymbolInfo(
                symbol=symbol,
                name=item.get("2. name", ""),
                exchange=item.get("4. region", ""),
                quote_type="EQUITY",
                source=self.name,
            ))
        return out

    def quote(self, symbol: str) -> Quote:
        data = self._call({"function": "GLOBAL_QUOTE", "symbol": symbol})
        row = (data.get("Global Quote") or {})
        price_raw = row.get("05. price")
        if not price_raw:
            raise SymbolNotFound(f"no quote for {symbol}")
        price = float(price_raw)
        previous = float(row.get("08. previous close") or 0) or None
        change = float(row.get("09. change") or 0)
        change_pct = float(row.get("10. change percent", "0").rstrip("%") or 0)
        return Quote(
            symbol=symbol,
            price=price,
            currency="USD",
            previous_close=previous,
            change=change,
            change_pct=change_pct,
            volume=float(row.get("06. volume") or 0) or None,
            market_time=str(row.get("07. latest trading day") or "") or None,
            source=self.name,
            fetched_at=utcnow_iso(),
        )

    def history(self, symbol: str, period: str, interval: str | None = None) -> History:
        data = self._call({"function": "TIME_SERIES_DAILY", "symbol": symbol, "outputsize": "full"})
        series = data.get("Time Series (Daily)") or {}
        if not series:
            raise ProviderError(f"no daily series for {symbol}")
        rows = sorted(series.items(), reverse=True)
        days = {"1M": 31, "3M": 93, "6M": 186, "1Y": 366, "2Y": 731, "5Y": 1827, "MAX": 10000}.get(period.upper(), 366)
        cutoff = time.time() - days * 86400
        candles: list[Candle] = []
        for date_str, values in reversed(rows):
            try:
                stamp = time.mktime(time.strptime(date_str, "%Y-%m-%d"))
            except ValueError:
                continue
            if stamp < cutoff:
                continue
            candles.append(Candle(
                ts=date_str,
                open=float(values["1. open"]),
                high=float(values["2. high"]),
                low=float(values["3. low"]),
                close=float(values["4. close"]),
                volume=float(values["5. volume"]),
            ))
        if not candles:
            raise ProviderError(f"no history within period {period} for {symbol}")
        return History(symbol=symbol, interval="1d", period=period.upper(), currency="USD",
                       candles=candles, source=self.name, fetched_at=utcnow_iso())

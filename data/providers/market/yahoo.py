from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from data.models import Candle, History, Quote, SymbolInfo
from data.providers.base import (
    HttpClient,
    MarketDataProvider,
    ProviderError,
    ProviderUnavailable,
    SymbolNotFound,
)
from database.sqlite_db import utcnow_iso

log = logging.getLogger(__name__)

PERIOD_MAP: dict[str, tuple[str, str, str]] = {
    "INTRA": ("1d", "5m", "intraday"),
    "1D": ("1d", "5m", "intraday"),
    "5D": ("5d", "15m", "intraday"),
    "1M": ("1mo", "1d", "daily"),
    "3M": ("3mo", "1d", "daily"),
    "6M": ("6mo", "1d", "daily"),
    "1Y": ("1y", "1d", "daily"),
    "2Y": ("2y", "1d", "daily"),
    "5Y": ("5y", "1d", "daily"),
    "MAX": ("max", "1wk", "weekly"),
}

DATE_INTERVALS = {"1d", "1wk", "1mo"}


def _iso(ts_epoch: int, granularity: str) -> str:
    dt = datetime.fromtimestamp(int(ts_epoch), tz=timezone.utc)
    if granularity in DATE_INTERVALS:
        return dt.strftime("%Y-%m-%d")
    return dt.strftime("%Y-%m-%dT%H:%M")


def _raw(value: Any) -> float | None:
    if isinstance(value, dict):
        value = value.get("raw")
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number else None


class YahooMarketProvider(MarketDataProvider):
    name = "yahoo"

    def __init__(self, config: dict[str, Any]):
        self.base_url = str(config.get("base_url", "https://query1.finance.yahoo.com")).rstrip("/")
        self.search_url = str(config.get("search_url", f"{self.base_url}/v1/finance/search"))
        network = config.get("_network", {})
        self.client = HttpClient(
            user_agent=str(network.get("user_agent", "personal-financial-terminal/0.1")),
            timeout=float(network.get("timeout_seconds", 10)),
            retries=int(network.get("retries", 2)),
        )

    def search(self, query: str, limit: int = 8) -> list[SymbolInfo]:
        data = self.client.get_json(
            self.search_url, params={"q": query, "quotesCount": limit, "newsCount": 0}
        )
        results: list[SymbolInfo] = []
        for item in data.get("quotes", []) or []:
            symbol = item.get("symbol")
            if not symbol:
                continue
            results.append(
                SymbolInfo(
                    symbol=symbol,
                    name=item.get("longname") or item.get("shortname") or "",
                    exchange=item.get("exchDisp") or item.get("exchange") or "",
                    quote_type=item.get("quoteType") or "",
                    sector=item.get("sector") or "",
                    industry=item.get("industry") or "",
                    source=self.name,
                )
            )
            if len(results) >= limit:
                break
        return results

    def quote(self, symbol: str) -> Quote:
        data = self.client.get_json(
            f"{self.base_url}/v8/finance/chart/{symbol}",
            params={"range": "1d", "interval": "5m"},
        )
        meta = self._meta(data, symbol)
        price = _raw(meta.get("regularMarketPrice"))
        if price is None:
            raise SymbolNotFound(f"no quote for {symbol}")
        previous_close = _raw(meta.get("chartPreviousClose")) or _raw(meta.get("previousClose"))
        change = _raw(meta.get("fulldayChange"))
        change_pct = _raw(meta.get("fulldayChangePercent"))
        if change is None and previous_close is not None:
            change = price - previous_close
        if change_pct is None and change is not None and previous_close:
            change_pct = (change / previous_close) * 100.0
        market_time = meta.get("regularMarketTime")
        return Quote(
            symbol=meta.get("symbol") or symbol,
            price=price,
            currency=meta.get("currency") or "",
            previous_close=previous_close,
            change=change,
            change_pct=change_pct,
            day_high=_raw(meta.get("regularMarketDayHigh")),
            day_low=_raw(meta.get("regularMarketDayLow")),
            volume=_raw(meta.get("regularMarketVolume")),
            fifty_two_high=_raw(meta.get("fiftyTwoWeekHigh")),
            fifty_two_low=_raw(meta.get("fiftyTwoWeekLow")),
            market_time=datetime.fromtimestamp(market_time, tz=timezone.utc).isoformat(timespec="seconds")
            if market_time
            else None,
            source=self.name,
            fetched_at=utcnow_iso(),
        )

    def history(self, symbol: str, period: str, interval: str | None = None) -> History:
        key = period.upper()
        if key not in PERIOD_MAP:
            raise ProviderError(f"unknown period {period}")
        range_value, default_interval, granularity = PERIOD_MAP[key]
        use_interval = interval or default_interval
        data = self.client.get_json(
            f"{self.base_url}/v8/finance/chart/{symbol}",
            params={"range": range_value, "interval": use_interval, "includeAdjustedClose": "true"},
        )
        result = self._result(data, symbol)
        timestamps = result.get("timestamp") or []
        quote_sets = (result.get("indicators", {}).get("quote") or [{}])[0]
        adj_sets = (result.get("indicators", {}).get("adjclose") or [{}])
        adjclose = adj_sets[0].get("adjclose") if adj_sets else None
        meta = result.get("meta", {})
        candles: list[Candle] = []
        closes = quote_sets.get("close") or []
        opens = quote_sets.get("open") or []
        highs = quote_sets.get("high") or []
        lows = quote_sets.get("low") or []
        volumes = quote_sets.get("volume") or []
        for index, ts in enumerate(timestamps):
            close = closes[index] if index < len(closes) else None
            if adjclose and index < len(adjclose) and adjclose[index] is not None:
                close = adjclose[index]
            if close is None:
                continue
            candles.append(
                Candle(
                    ts=_iso(ts, use_interval),
                    open=_raw(opens[index]) if index < len(opens) else None,
                    high=_raw(highs[index]) if index < len(highs) else None,
                    low=_raw(lows[index]) if index < len(lows) else None,
                    close=float(close),
                    volume=_raw(volumes[index]) if index < len(volumes) else None,
                )
            )
        if not candles:
            raise ProviderError(f"no history returned for {symbol}")
        return History(
            symbol=meta.get("symbol") or symbol,
            interval=use_interval,
            period=key,
            currency=meta.get("currency") or "",
            candles=candles,
            source=self.name,
            fetched_at=utcnow_iso(),
        )

    def _result(self, data: dict[str, Any], symbol: str) -> dict[str, Any]:
        chart = data.get("chart", {})
        if chart.get("error"):
            error = chart["error"]
            description = str(error.get("description") or error.get("code") or "unknown error")
            if "delisted" in description.lower() or "not found" in description.lower():
                raise SymbolNotFound(f"{symbol}: {description}")
            raise ProviderError(f"{symbol}: {description}")
        results = chart.get("result") or []
        if not results:
            raise SymbolNotFound(f"no data for {symbol}")
        return results[0]

    def _meta(self, data: dict[str, Any], symbol: str) -> dict[str, Any]:
        return self._result(data, symbol).get("meta", {})

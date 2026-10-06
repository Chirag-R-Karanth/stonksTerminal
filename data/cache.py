from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

import pandas as pd

from app import paths
from app.config import Config
from data.models import (
    STATUS_CACHED,
    STATUS_DEMO,
    STATUS_ERROR,
    STATUS_LIVE,
    STATUS_OFFLINE,
    STATUS_STALE,
    DataResult,
    Fundamentals,
    History,
    MacroObservation,
    MacroSeries,
    Quote,
    Statements,
)
from data.providers.base import ProviderError, ProviderUnavailable, RateLimited, SymbolNotFound
from database.duck import AnalyticStore
from database.repositories import FetchLogRepo, JsonCacheRepo, ProvenanceRepo
from database.sqlite_db import Database, parse_iso, utcnow_iso

log = logging.getLogger(__name__)

PERIOD_DAYS: dict[str, int] = {
    "INTRA": 1, "1D": 1, "5D": 5, "1M": 31, "3M": 93, "6M": 186,
    "1Y": 366, "2Y": 731, "5Y": 1827, "MAX": 4000,
}

PERIOD_INTERVAL: dict[str, str] = {
    "INTRA": "5m", "1D": "5m", "5D": "15m", "1M": "1d", "3M": "1d", "6M": "1d",
    "1Y": "1d", "2Y": "1d", "5Y": "1d", "MAX": "1wk",
}


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _age_seconds(fetched_at: str | None) -> float:
    ts = parse_iso(fetched_at) if fetched_at else None
    if ts is None:
        return float("inf")
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - ts).total_seconds()


class DataCache:
    def __init__(self, db: Database, store: AnalyticStore, config: Config):
        self.db = db
        self.store = store
        self.config = config
        cache_cfg = config.section("data.cache")
        self.quote_ttl = float(cache_cfg.get("quote_ttl_seconds", 60))
        self.price_ttl = float(cache_cfg.get("price_ttl_seconds", 300))
        self.fundamental_ttl = float(cache_cfg.get("fundamental_ttl_seconds", 21600))
        self.macro_ttl = float(cache_cfg.get("macro_ttl_seconds", 86400))
        self.history_days = int(cache_cfg.get("history_days", 4000))
        self.quote_cache = JsonCacheRepo(db, "quote_cache")
        self.fundamentals_cache = JsonCacheRepo(db, "fundamentals_cache")
        self.statements_cache = JsonCacheRepo(db, "statements_cache")
        self.macro_cache = JsonCacheRepo(db, "macro_cache")
        self.fetch_log = FetchLogRepo(db)
        self.provenance = ProvenanceRepo(db)

    def get_quote(
        self,
        symbol: str,
        provider_name: str,
        fetch: Callable[[], Quote],
        force: bool = False,
    ) -> DataResult[Quote]:
        def serialize(quote: Quote) -> dict[str, Any]:
            return quote.to_dict()

        def deserialize(payload: dict[str, Any]) -> Quote:
            return Quote.from_dict(payload)

        return self._generic(
            key=symbol,
            cache=self.quote_cache,
            ttl=self.quote_ttl,
            entity=symbol,
            data_type="quote",
            provider_name=provider_name,
            fetch=lambda: (fetch(), None),
            serialize=serialize,
            deserialize=deserialize,
            force=force,
        )

    def get_fundamentals(
        self,
        symbol: str,
        provider_name: str,
        fetch: Callable[[], Fundamentals],
        force: bool = False,
    ) -> DataResult[Fundamentals]:
        return self._generic(
            key=symbol,
            cache=self.fundamentals_cache,
            ttl=self.fundamental_ttl,
            entity=symbol,
            data_type="fundamentals",
            provider_name=provider_name,
            fetch=lambda: (fetch(), None),
            serialize=lambda f: f.to_dict(),
            deserialize=Fundamentals.from_dict,
            force=force,
            currency_getter=lambda f: f.currency,
        )

    def get_statements(
        self,
        symbol: str,
        period: str,
        provider_name: str,
        fetch: Callable[[], Statements],
        force: bool = False,
    ) -> DataResult[Statements]:
        return self._generic(
            key=f"{symbol}:{period}",
            cache=self.statements_cache,
            ttl=self.fundamental_ttl,
            entity=symbol,
            data_type=f"statements:{period}",
            provider_name=provider_name,
            fetch=lambda: (fetch(), None),
            serialize=lambda s: s.to_dict(),
            deserialize=Statements.from_dict,
            force=force,
            currency_getter=lambda s: s.currency,
        )

    def get_macro(
        self,
        series_id: str,
        provider_name: str,
        fetch: Callable[[], MacroSeries],
        force: bool = False,
    ) -> DataResult[MacroSeries]:
        return self._generic(
            key=series_id,
            cache=self.macro_cache,
            ttl=self.macro_ttl,
            entity=series_id,
            data_type="macro",
            provider_name=provider_name,
            fetch=lambda: (fetch(), None),
            serialize=lambda m: {
                "id": m.id, "title": m.title, "units": m.units, "source": m.source,
                "fetched_at": m.fetched_at,
                "observations": [{"date": o.date, "value": o.value} for o in m.observations],
            },
            deserialize=lambda p: MacroSeries(
                id=p.get("id", series_id),
                title=p.get("title", series_id),
                units=p.get("units", ""),
                source=p.get("source", ""),
                fetched_at=p.get("fetched_at", ""),
                observations=[MacroObservation(date=o["date"], value=float(o["value"]))
                              for o in p.get("observations", [])],
            ),
            force=force,
        )

    def _generic(
        self,
        key: str,
        cache: JsonCacheRepo,
        ttl: float,
        entity: str,
        data_type: str,
        provider_name: str,
        fetch: Callable[[], tuple[Any, str | None]],
        serialize: Callable[[Any], dict[str, Any]],
        deserialize: Callable[[dict[str, Any]], Any],
        force: bool,
        currency_getter: Callable[[Any], str | None] | None = None,
    ) -> DataResult[Any]:
        cached = cache.get(key)
        if cached is not None and not force and _age_seconds(cached[1]) <= ttl:
            data = deserialize(cached[0])
            return DataResult(
                data=data, status=STATUS_CACHED, provider=provider_name,
                fetched_at=cached[1], message="cached",
            )
        try:
            data, _ = fetch()
        except Exception as exc:
            return self._fallback(exc, cached, provider_name, entity, data_type, deserialize)
        fetched_at = cache.put(key, serialize(data), provider_name)
        self.fetch_log.record(entity, data_type, provider_name, True)
        is_demo = bool(getattr(data, "is_demo", False)) or provider_name == "demo"
        currency = currency_getter(data) if currency_getter else getattr(data, "currency", None)
        self.provenance.record(
            entity=entity, field=data_type, data_type=data_type,
            provider=provider_name, source=getattr(data, "source", provider_name) or provider_name,
            currency=currency,
        )
        return DataResult(
            data=data,
            status=STATUS_DEMO if is_demo else STATUS_LIVE,
            provider=provider_name,
            fetched_at=fetched_at,
            message="" if not is_demo else "DEMO DATA — not real market data",
        )

    def _fallback(
        self,
        exc: Exception,
        cached: tuple[Any, str] | None,
        provider_name: str,
        entity: str,
        data_type: str,
        deserialize: Callable[[dict[str, Any]], Any],
    ) -> DataResult[Any]:
        detail = f"{type(exc).__name__}: {exc}"
        self.fetch_log.record(entity, data_type, provider_name, False, detail[:500])
        log.warning("fetch failed for %s %s: %s", entity, data_type, detail)
        offline = isinstance(exc, (ProviderUnavailable, ConnectionError, OSError))
        if cached is None:
            return DataResult(
                data=None,
                status=STATUS_OFFLINE if offline else STATUS_ERROR,
                provider=provider_name,
                message=self._human_error(exc),
            )
        data = deserialize(cached[0])
        age = _age_seconds(cached[1])
        status = STATUS_OFFLINE if offline and age > ttl_seconds(data_type, self) else STATUS_STALE
        if age <= ttl_seconds(data_type, self):
            status = STATUS_CACHED
        return DataResult(
            data=data,
            status=status,
            provider=provider_name,
            fetched_at=cached[1],
            message=f"{self._human_error(exc)} (using cached data from {cached[1]})",
        )

    @staticmethod
    def _human_error(exc: Exception) -> str:
        if isinstance(exc, SymbolNotFound):
            return str(exc)
        if isinstance(exc, RateLimited):
            return "provider rate limit reached"
        if isinstance(exc, ProviderUnavailable):
            return f"provider unavailable: {exc}"
        if isinstance(exc, ProviderError):
            return str(exc)
        if isinstance(exc, (ConnectionError, OSError)):
            return "network unavailable"
        return f"{type(exc).__name__}: {exc}"

    def get_history(
        self,
        symbol: str,
        period: str,
        provider_name: str,
        fetch: Callable[[str], History],
        force: bool = False,
    ) -> DataResult[History]:
        period_key = period.upper()
        interval = PERIOD_INTERVAL.get(period_key, "1d")
        days = min(PERIOD_DAYS.get(period_key, 366), self.history_days)
        start = _utcnow_naive() - timedelta(days=days)
        cached_df = self.store.read_prices(symbol, interval=interval, start=start)
        if not force and not cached_df.empty and self._covers(cached_df, start):
            newest = cached_df["ts"].max()
            age = (_utcnow_naive() - pd.Timestamp(newest).to_pydatetime().replace(tzinfo=None)).total_seconds()
            if age <= self.price_ttl:
                history = self._frame_to_history(symbol, period_key, interval, cached_df, provider_name)
                return DataResult(
                    data=history, status=STATUS_CACHED, provider=provider_name,
                    fetched_at=cached_df["ts"].max().isoformat(), message="cached",
                )
            stale_df = cached_df
        else:
            stale_df = cached_df
        try:
            history = fetch(symbol)
        except Exception as exc:
            return self._history_fallback(exc, symbol, period_key, interval, stale_df, provider_name)
        frame = pd.DataFrame([{
            "ts": pd.to_datetime(c.ts),
            "open": c.open, "high": c.high, "low": c.low,
            "close": c.close, "volume": c.volume,
        } for c in history.candles])
        if frame.empty:
            return DataResult(data=None, status=STATUS_ERROR, provider=provider_name,
                              message="provider returned no candles")
        frame["ts"] = pd.to_datetime(frame["ts"], utc=False)
        self.store.write_prices(symbol, frame, interval=history.interval)
        self.fetch_log.record(symbol, f"history:{period_key}", provider_name, True)
        self.provenance.record(
            entity=symbol, field="history", data_type=f"history:{period_key}",
            provider=provider_name, source=history.source or provider_name,
            currency=history.currency,
        )
        status = STATUS_DEMO if history.is_demo or provider_name == "demo" else STATUS_LIVE
        return DataResult(
            data=history, status=status, provider=provider_name,
            fetched_at=history.fetched_at,
            message="" if status == STATUS_LIVE else "DEMO DATA — not real market data",
        )

    def _covers(self, frame: pd.DataFrame, start: datetime) -> bool:
        if frame.empty:
            return False
        oldest = pd.Timestamp(frame["ts"].min()).to_pydatetime().replace(tzinfo=None)
        return oldest <= start + timedelta(days=3)

    def _history_fallback(
        self,
        exc: Exception,
        symbol: str,
        period_key: str,
        interval: str,
        cached_df: pd.DataFrame,
        provider_name: str,
    ) -> DataResult[History]:
        detail = f"{type(exc).__name__}: {exc}"
        self.fetch_log.record(symbol, f"history:{period_key}", provider_name, False, detail[:500])
        log.warning("history fetch failed for %s: %s", symbol, detail)
        if cached_df.empty:
            offline = isinstance(exc, (ProviderUnavailable, ConnectionError, OSError))
            return DataResult(
                data=None,
                status=STATUS_OFFLINE if offline else STATUS_ERROR,
                provider=provider_name,
                message=self._human_error(exc),
            )
        history = self._frame_to_history(symbol, period_key, interval, cached_df, provider_name)
        last_ok = self.fetch_log.last_ok(symbol, f"history:{period_key}")
        fetched_at = last_ok.isoformat(timespec="seconds") if last_ok else cached_df["ts"].max().isoformat()
        return DataResult(
            data=history,
            status=STATUS_STALE,
            provider=provider_name,
            fetched_at=fetched_at,
            message=f"{self._human_error(exc)} (cached through {fetched_at})",
        )

    @staticmethod
    def _frame_to_history(
        symbol: str, period_key: str, interval: str, frame: pd.DataFrame, provider_name: str
    ) -> History:
        from data.models import Candle

        candles = [
            Candle(
                ts=row["ts"].strftime("%Y-%m-%dT%H:%M") if interval not in ("1d", "1wk", "1mo")
                else row["ts"].strftime("%Y-%m-%d"),
                open=None if pd.isna(row["open"]) else float(row["open"]),
                high=None if pd.isna(row["high"]) else float(row["high"]),
                low=None if pd.isna(row["low"]) else float(row["low"]),
                close=float(row["close"]),
                volume=None if pd.isna(row["volume"]) else float(row["volume"]),
            )
            for _, row in frame.iterrows()
        ]
        return History(
            symbol=symbol, interval=interval, period=period_key, currency="",
            candles=candles, source=provider_name, fetched_at=utcnow_iso(),
        )

    def last_success(self, entity: str, data_type: str) -> str | None:
        ts = self.fetch_log.last_ok(entity, data_type)
        return ts.isoformat(timespec="seconds") if ts else None


def ttl_seconds(data_type: str, cache: DataCache) -> float:
    if data_type == "quote":
        return cache.quote_ttl
    if data_type.startswith("history"):
        return cache.price_ttl
    if data_type.startswith("macro"):
        return cache.macro_ttl
    return cache.fundamental_ttl

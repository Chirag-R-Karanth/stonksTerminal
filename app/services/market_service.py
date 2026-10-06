from __future__ import annotations

import logging
import threading
from typing import Iterable

from data.cache import DataCache
from data.models import DataResult, History, Quote, SymbolInfo
from data.providers.base import MarketDataProvider, SymbolNotFound
from database.repositories import SymbolMetaRepo

log = logging.getLogger(__name__)


class MarketService:
    def __init__(
        self,
        provider: MarketDataProvider,
        cache: DataCache,
        symbol_repo: SymbolMetaRepo,
    ):
        self.provider = provider
        self.cache = cache
        self.symbol_repo = symbol_repo
        self._lock = threading.Lock()

    @property
    def name(self) -> str:
        return self.provider.name

    def search_local(self, query: str, limit: int = 8) -> list[SymbolInfo]:
        rows = self.symbol_repo.search(query, limit)
        return [
            SymbolInfo(
                symbol=r["symbol"],
                name=r.get("name") or "",
                exchange=r.get("exchange") or "",
                quote_type=r.get("quote_type") or "",
                sector=r.get("sector") or "",
                industry=r.get("industry") or "",
                currency=r.get("currency") or "",
                source=r.get("source") or "",
            )
            for r in rows
        ]

    def search(self, query: str, limit: int = 8) -> list[SymbolInfo]:
        with self._lock:
            try:
                results = self.provider.search(query, limit)
            except Exception as exc:
                local = self.search_local(query, limit)
                if local:
                    log.warning("provider search failed, using local metadata: %s", exc)
                    return local
                raise
        for info in results:
            self._store(info)
        return results

    def resolve(self, symbol: str) -> SymbolInfo:
        wanted = symbol.upper()
        local = self.symbol_repo.get(wanted)
        if local:
            return SymbolInfo(
                symbol=local["symbol"],
                name=local.get("name") or "",
                exchange=local.get("exchange") or "",
                quote_type=local.get("quote_type") or "",
                sector=local.get("sector") or "",
                industry=local.get("industry") or "",
                currency=local.get("currency") or "",
                source=local.get("source") or "",
            )
        results = self.search(wanted, limit=6)
        for info in results:
            if info.symbol.upper() == wanted:
                return info
        if results:
            return results[0]
        raise SymbolNotFound(f"unknown symbol {symbol}")

    def quote(self, symbol: str, force: bool = False) -> DataResult[Quote]:
        return self.cache.get_quote(
            symbol, self.provider.name, lambda: self.provider.quote(symbol), force=force
        )

    def history(self, symbol: str, period: str = "1Y", force: bool = False) -> DataResult[History]:
        return self.cache.get_history(
            symbol, period, self.provider.name,
            lambda sym: self.provider.history(sym, period), force=force,
        )

    def quotes(self, symbols: Iterable[str], force: bool = False) -> dict[str, DataResult[Quote]]:
        return {symbol: self.quote(symbol, force=force) for symbol in symbols}

    def _store(self, info: SymbolInfo) -> None:
        try:
            self.symbol_repo.upsert(info.to_dict())
        except Exception as exc:
            log.warning("failed to store symbol meta for %s: %s", info.symbol, exc)

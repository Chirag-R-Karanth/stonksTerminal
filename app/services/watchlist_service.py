from __future__ import annotations

import logging
from typing import Any

from app.services.market_service import MarketService
from database.repositories import SettingsRepo, WatchlistRepo

log = logging.getLogger(__name__)

DEFAULT_LIST = "default"


class WatchlistService:
    def __init__(self, repo: WatchlistRepo, settings: SettingsRepo, market: MarketService):
        self.repo = repo
        self.settings = settings
        self.market = market

    def ensure(self) -> str:
        lists = self.repo.list_all()
        if not lists:
            self.repo.create(DEFAULT_LIST)
            lists = self.repo.list_all()
        active = str(self.settings.get("watchlist.active", DEFAULT_LIST))
        if not any(wl["name"] == active for wl in lists):
            active = lists[0]["name"]
            self.settings.set("watchlist.active", active)
        return active

    def names(self) -> list[str]:
        return [wl["name"] for wl in self.repo.list_all()]

    def set_active(self, name: str) -> bool:
        if self.repo.get(name) is None:
            return False
        self.settings.set("watchlist.active", name)
        return True

    def create(self, name: str) -> bool:
        if self.repo.get(name) is not None:
            return False
        self.repo.create(name)
        return True

    def delete(self, name: str) -> bool:
        if name.lower() == DEFAULT_LIST:
            return False
        ok = self.repo.delete(name)
        if ok and str(self.settings.get("watchlist.active", "")).lower() == name.lower():
            self.settings.set("watchlist.active", DEFAULT_LIST)
            self.ensure()
        return ok

    def add(self, name: str, symbol: str) -> bool:
        if self.repo.get(name) is None:
            return False
        self.market.resolve(symbol)
        return self.repo.add(name, symbol.upper())

    def remove(self, name: str, symbol: str) -> bool:
        if self.repo.get(name) is None:
            return False
        return self.repo.remove(name, symbol.upper())

    def rows(self, name: str | None = None, force: bool = False) -> list[dict[str, Any]]:
        active = name or self.ensure()
        wl = self.repo.get(active)
        if wl is None:
            raise KeyError(f"unknown watchlist: {active}")
        out: list[dict[str, Any]] = []
        for symbol in wl["symbols"]:
            meta = self.market.symbol_repo.get(symbol) or {}
            result = self.market.quote(symbol, force=force)
            quote = result.data
            out.append(
                {
                    "symbol": symbol,
                    "name": meta.get("name") or "",
                    "sector": meta.get("sector") or "",
                    "price": quote.price if quote else None,
                    "change_pct": quote.change_pct if quote else None,
                    "currency": quote.currency if quote else (meta.get("currency") or ""),
                    "market_cap": quote.market_cap if quote else None,
                    "status": result.status,
                    "message": result.message or "",
                    "fetched_at": result.fetched_at,
                }
            )
        return out

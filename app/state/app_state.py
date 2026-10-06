from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable

from analytics.api import Analytics
from analytics.engine import AnalyticsEngine
from app import paths
from app.commands.registry import help_lines
from app.config import Config
from app.services.macro_service import MacroService
from app.services.market_service import MarketService
from app.services.news_service import NewsService
from app.services.portfolio_service import PortfolioService
from app.services.screener_service import ScreenerService
from app.services.security_service import SecurityService
from app.services.watchlist_service import WatchlistService
from data.cache import DataCache
from data.providers.registry import ProviderRegistry
from database.duck import AnalyticStore
from database.repositories import (
    FetchLogRepo,
    HistoryRepo,
    NewsCacheRepo,
    PortfolioRepo,
    ProvenanceRepo,
    ScreenRepo,
    SettingsRepo,
    SymbolMetaRepo,
    WatchlistRepo,
)
from database.sqlite_db import Database

log = logging.getLogger(__name__)

Listener = Callable[[str, dict[str, Any]], None]


class AppState:
    def __init__(self, config: Config, db: Database, store: AnalyticStore):
        self.config = config
        self.db = db
        self.store = store
        self.providers = ProviderRegistry(config)
        self.cache = DataCache(db, store, config)
        rscript = str(config.get("analytics.rscript", "Rscript"))
        self.r_engine = AnalyticsEngine(
            rscript=rscript,
            timeout=float(config.get("analytics.timeout_seconds", 30)),
        )
        self.analytics = Analytics(
            self.r_engine,
            risk_free=float(config.get("analytics.risk_free_rate", 0.04)),
            periods_per_year=int(config.get("analytics.trading_days", 252)),
        )
        self.settings = SettingsRepo(db)
        self.history = HistoryRepo(db, limit=int(config.get("terminal.history_limit", 500)))
        self.symbol_meta = SymbolMetaRepo(db)
        self.screens = ScreenRepo(db)
        self.watchlist_repo = WatchlistRepo(db)
        self.portfolio_repo = PortfolioRepo(db)
        self.news_cache = NewsCacheRepo(db)
        self.fetch_log = FetchLogRepo(db)
        self.provenance = ProvenanceRepo(db)

        self.market = MarketService(self.providers.market, self.cache, self.symbol_meta)
        self.security = SecurityService(
            self.market, self.providers.fundamentals, self.cache, config, self.analytics
        )
        self.watchlists = WatchlistService(self.watchlist_repo, self.settings, self.market)
        self.portfolio = PortfolioService(
            self.portfolio_repo, self.symbol_meta, self.market, self.analytics, config
        )
        self.news = NewsService(self.providers.news, self.news_cache, config)
        self.macro = MacroService(self.providers.macro, self.cache, config)
        self.screener = ScreenerService(
            db, store, self.security, self.watchlists, self.screens,
            self.symbol_meta, self.watchlist_repo,
            lambda: [h["symbol"] for h in self.portfolio.holdings()],
            config,
        )

        self.demo_mode = bool(config.get("data.demo_mode", False))
        self.offline = False
        self._listeners: list[Listener] = []
        self._r_available: bool | None = None
        self.current_view_fn: Callable[[], dict[str, Any] | None] | None = None
        self.watchlists.ensure()

    @classmethod
    def create(cls, config: Config | None = None) -> "AppState":
        config = config or Config.load()
        db = Database()
        db.migrate()
        store = AnalyticStore(paths.parquet_dir(), paths.duckdb_path())
        return cls(config, db, store)

    def close(self) -> None:
        try:
            self.r_engine.shutdown()
        except Exception as exc:
            log.warning("r engine shutdown failed: %s", exc)
        try:
            self.store.close()
        except Exception as exc:
            log.warning("store close failed: %s", exc)
        self.db.close()

    def add_listener(self, callback: Listener) -> None:
        self._listeners.append(callback)

    def notify(self, event: str, payload: dict[str, Any] | None = None) -> None:
        data = payload or {}
        for callback in list(self._listeners):
            try:
                callback(event, data)
            except Exception as exc:
                log.warning("listener %s failed: %s", getattr(callback, "__name__", callback), exc)

    def set_offline(self, offline: bool) -> None:
        if offline != self.offline:
            self.offline = offline
            self.notify("offline", {"offline": offline})

    @property
    def r_available(self) -> bool:
        if self._r_available is None:
            try:
                self._r_available = bool(self.analytics.available)
            except Exception as exc:
                log.warning("r probe failed: %s", exc)
                self._r_available = False
        return self._r_available

    def status_summary(self) -> dict[str, Any]:
        providers = self.providers.describe()
        return {
            "providers": providers,
            "demo_mode": self.demo_mode,
            "offline": self.offline,
            "r_available": self.r_available,
            "db_path": str(self.db.path),
            "data_dir": str(paths.data_dir()),
            "quote_ttl": self.cache.quote_ttl,
            "news_ttl": float(self.config.get("data.cache.news_ttl_seconds", 300)),
            "universe_size": len(self.screener.universe()),
            "watchlists": self.watchlists.names(),
            "help": help_lines(),
        }

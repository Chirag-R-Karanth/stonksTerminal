from __future__ import annotations

import logging
from typing import Any, Callable

from app.config import Config
from data.providers.base import (
    FundamentalDataProvider,
    MacroDataProvider,
    MarketDataProvider,
    NewsProvider,
)
from data.providers.demo import (
    DemoFundamentalProvider,
    DemoMacroProvider,
    DemoMarketProvider,
    DemoNewsProvider,
)
from data.providers.fundamentals.yahoo import YahooFundamentalProvider
from data.providers.macro.fred import FredMacroProvider
from data.providers.market.alphavantage import AlphaVantageMarketProvider
from data.providers.market.yahoo import YahooMarketProvider
from data.providers.news.rss import RssNewsProvider

log = logging.getLogger(__name__)


class ProviderRegistry:
    def __init__(self, config: Config):
        self.config = config
        demo_mode = bool(config.get("data.demo_mode", False))
        self.market = self._build_market(demo_mode)
        self.fundamentals = self._build_fundamentals(demo_mode)
        self.news = self._build_news(demo_mode)
        self.macro = self._build_macro(demo_mode)
        log.info(
            "providers: market=%s fundamentals=%s news=%s macro=%s",
            self.market.name, self.fundamentals.name, self.news.name, self.macro.name,
        )

    def _provider_config(self, name: str) -> dict[str, Any]:
        cfg = self.config.section(f"providers.{name}")
        cfg["_network"] = self.config.section("network")
        return cfg

    def _build_market(self, demo_mode: bool) -> MarketDataProvider:
        if demo_mode:
            return DemoMarketProvider()
        name = str(self.config.get("data.market_provider", "yahoo"))
        if name == "alphavantage":
            cfg = self._provider_config("alpha_vantage")
            cfg["_api_key"] = self.config.secret(
                "providers.alpha_vantage.api_key",
                env=str(self.config.get("providers.alpha_vantage.api_key_env", "ALPHA_VANTAGE_API_KEY")),
            )
            return AlphaVantageMarketProvider(cfg)
        return YahooMarketProvider(self._provider_config("yahoo"))

    def _build_fundamentals(self, demo_mode: bool) -> FundamentalDataProvider:
        if demo_mode:
            return DemoFundamentalProvider()
        name = str(self.config.get("data.fundamentals_provider", "yahoo"))
        if name == "demo":
            return DemoFundamentalProvider()
        return YahooFundamentalProvider(self._provider_config("yahoo"))

    def _build_news(self, demo_mode: bool) -> NewsProvider:
        if demo_mode:
            return DemoNewsProvider()
        name = str(self.config.get("data.news_provider", "yahoo_rss"))
        if name == "demo":
            return DemoNewsProvider()
        cfg = self._provider_config("rss")
        cfg["_search_url"] = str(self.config.get("providers.yahoo.search_url"))
        return RssNewsProvider(cfg)

    def _build_macro(self, demo_mode: bool) -> MacroDataProvider:
        if demo_mode:
            return DemoMacroProvider()
        name = str(self.config.get("data.macro_provider", "fred"))
        if name == "demo":
            return DemoMacroProvider()
        cfg = self._provider_config("fred")
        cfg["_api_key"] = self.config.secret(
            "providers.fred.api_key",
            env=str(self.config.get("providers.fred.api_key_env", "FRED_API_KEY")),
        )
        return FredMacroProvider(cfg)

    def describe(self) -> dict[str, str]:
        return {
            "market": self.market.name,
            "fundamentals": self.fundamentals.name,
            "news": self.news.name,
            "macro": self.macro.name,
        }

from __future__ import annotations

import logging
import threading
from typing import Any

from analytics.api import Analytics
from app.config import Config
from app.services.market_service import MarketService
from data.cache import DataCache
from data.models import STATUS_ERROR, DataResult, Fundamentals, Statements, SymbolInfo
from data.providers.base import FundamentalDataProvider

log = logging.getLogger(__name__)

DCF_ASSUMPTION_DEFAULTS: dict[str, float] = {
    "wacc": 0.09,
    "terminal_growth": 0.025,
    "tax_rate": 0.21,
    "nwc_pct": 0.05,
    "years": 10,
}

STATEMENT_GROWTH_SERIES = "revenue"


class SecurityService:
    def __init__(
        self,
        market: MarketService,
        provider: FundamentalDataProvider,
        cache: DataCache,
        config: Config,
        analytics: Analytics,
    ):
        self.market = market
        self.provider = provider
        self.cache = cache
        self.config = config
        self.analytics = analytics
        self._lock = threading.Lock()

    def fundamentals(self, symbol: str, force: bool = False) -> DataResult[Fundamentals]:
        return self.cache.get_fundamentals(
            symbol, self.provider.name, lambda: self.provider.snapshot(symbol), force=force
        )

    def statements(self, symbol: str, period: str = "annual", force: bool = False) -> DataResult[Statements]:
        return self.cache.get_statements(
            symbol, period, self.provider.name,
            lambda: self.provider.statements(symbol, period), force=force,
        )

    def profile(self, symbol: str) -> SymbolInfo:
        try:
            with self._lock:
                info = self.provider.profile(symbol)
            if info.symbol:
                self.market.symbol_repo.upsert(info.to_dict())
            return info
        except Exception as exc:
            log.warning("profile fetch failed for %s: %s", symbol, exc)
            return self.market.resolve(symbol)

    def peers(self, symbol: str) -> list[str]:
        upper = symbol.upper().replace(".NS", "")
        table = self.config.get("peers", {}) or {}
        direct = table.get(upper) or table.get(symbol.upper())
        if direct:
            return list(direct)
        found: list[str] = []
        for key, values in table.items():
            if upper in [str(v).replace(".NS", "") for v in values]:
                found.append(key)
        return found[:4]

    def valuation(self, symbol: str) -> DataResult[dict[str, Any]]:
        fundamentals = self.fundamentals(symbol)
        if fundamentals.data is None:
            return DataResult(
                data=None, status=fundamentals.status, message=fundamentals.message,
                provider=fundamentals.provider, fetched_at=fundamentals.fetched_at,
            )
        fields = fundamentals.data.fields
        try:
            multiples = self.analytics.multiples(
                {
                    "shares": fields.get("shares_outstanding"),
                    "market_cap": fields.get("market_cap"),
                    "revenue": fields.get("revenue"),
                    "gross_profit": None,
                    "operating_income": None,
                    "ebitda": fields.get("ebitda"),
                    "net_income": (
                        fields.get("eps_trailing") * fields.get("shares_outstanding")
                        if fields.get("eps_trailing") and fields.get("shares_outstanding")
                        else None
                    ),
                    "free_cash_flow": fields.get("free_cash_flow"),
                    "ebit": None,
                    "shareholders_equity": None,
                    "total_debt": fields.get("total_debt"),
                    "cash": fields.get("total_cash"),
                    "dividend_per_share": (
                        fields.get("dividend_rate") if fields.get("dividend_rate") else None
                    ),
                },
                price=fields.get("price"),
            )
        except Exception as exc:
            log.warning("R multiples failed for %s: %s", symbol, exc)
            multiples = {}
        return DataResult(
            data={"fields": fields, "multiples": multiples, "text_fields": fundamentals.data.text_fields},
            status=fundamentals.status,
            message=fundamentals.message,
            provider=fundamentals.provider,
            fetched_at=fundamentals.fetched_at,
        )

    def dcf_model(self, symbol: str) -> DataResult[dict[str, Any]]:
        fundamentals = self.fundamentals(symbol)
        if fundamentals.data is None:
            return DataResult(
                data=None, status=fundamentals.status, message=fundamentals.message,
                provider=fundamentals.provider, fetched_at=fundamentals.fetched_at,
            )
        statements = self.statements(symbol, "annual")
        if statements.data is None or not statements.data.periods:
            return DataResult(
                data=None, status=statements.status,
                message=statements.message or "no statements available for model",
                provider=statements.provider, fetched_at=statements.fetched_at,
            )
        periods = list(reversed(statements.data.periods))
        latest = periods[-1]
        revenue = latest.fields.get("revenue")
        operating_income = latest.fields.get("operating_income")
        if not revenue or not operating_income:
            return DataResult(
                data=None, status=statements.status,
                message="insufficient statement data for model", provider=statements.provider,
            )
        fields = fundamentals.data.fields
        revenue_series = [p.fields.get("revenue") for p in periods if p.fields.get("revenue")]
        growth = 0.05
        if len(revenue_series) >= 3:
            try:
                cagr = self.analytics.performance(revenue_series).cagr
                if cagr is not None and -0.5 < cagr < 0.6:
                    growth = cagr
            except Exception as exc:
                log.warning("growth calc failed for %s: %s", symbol, exc)
        assumptions = dict(DCF_ASSUMPTION_DEFAULTS)
        config_assumptions = self.config.section("valuation") or {}
        for key, value in config_assumptions.items():
            if isinstance(value, (int, float)) and key in assumptions:
                assumptions[key] = float(value)
        total_debt = fields.get("total_debt") or 0.0
        cash = fields.get("total_cash") or 0.0
        capex_ratio = 0.04
        capex = latest.fields.get("capital_expenditure")
        if capex and revenue:
            capex_ratio = min(max(abs(capex) / revenue, 0.0), 0.3)
        try:
            result = self.analytics.dcf(
                revenue=revenue,
                shares=fields.get("shares_outstanding"),
                growth=growth,
                ebit_margin=operating_income / revenue,
                wacc=assumptions["wacc"],
                terminal_growth=assumptions["terminal_growth"],
                tax_rate=assumptions["tax_rate"],
                capex_pct=capex_ratio,
                nwc_pct=assumptions["nwc_pct"],
                da_pct=0.0,
                net_debt=total_debt - cash,
                price=fields.get("price"),
                years=int(assumptions["years"]),
            )
        except Exception as exc:
            return DataResult(
                data=None, status=STATUS_ERROR,
                message=f"model failed: {exc}", provider=self.provider.name,
            )
        return DataResult(
            data={
                "assumptions": {
                    **assumptions,
                    "revenue": revenue,
                    "growth": growth,
                    "ebit_margin": operating_income / revenue,
                    "capex_pct": capex_ratio,
                    "net_debt": total_debt - cash,
                    "shares": fields.get("shares_outstanding"),
                    "price": fields.get("price"),
                },
                "model": result,
            },
            status=fundamentals.status,
            message=fundamentals.message,
            provider=self.provider.name,
            fetched_at=fundamentals.fetched_at,
        )

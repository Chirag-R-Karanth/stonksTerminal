from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any

from data.models import Fundamentals, Statements, StatementPeriod, SymbolInfo
from data.providers.base import (
    ConfigError,
    FundamentalDataProvider,
    HttpClient,
    ProviderError,
    ProviderUnavailable,
    SymbolNotFound,
)
from database.sqlite_db import utcnow_iso

log = logging.getLogger(__name__)

STATEMENT_TYPES: dict[str, str] = {
    "revenue": "TotalRevenue",
    "gross_profit": "GrossProfit",
    "operating_income": "OperatingIncome",
    "net_income": "NetIncome",
    "diluted_eps": "DilutedEPS",
    "ebitda": "EBITDA",
    "total_assets": "TotalAssets",
    "total_liabilities": "TotalLiabilitiesNetMinorityInterest",
    "shareholders_equity": "StockholdersEquity",
    "cash": "CashAndCashEquivalents",
    "total_debt": "TotalDebt",
    "operating_cash_flow": "OperatingCashFlow",
    "free_cash_flow": "FreeCashFlow",
    "research_and_development": "ResearchAndDevelopment",
    "capital_expenditure": "CapitalExpenditure",
}

REVERSE_STATEMENT_TYPES = {v: k for k, v in STATEMENT_TYPES.items()}


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


def _earnings_date(calendar: dict[str, Any]) -> str:
    dates = calendar.get("earningsDate") or []
    if not dates:
        return ""
    value = dates[0]
    if isinstance(value, dict):
        value = value.get("raw")
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc).date().isoformat()
    if isinstance(value, str):
        return value[:10]
    return ""


class YahooFundamentalProvider(FundamentalDataProvider):
    name = "yahoo"

    def __init__(self, config: dict[str, Any]):
        self.base_url = str(config.get("base_url", "https://query1.finance.yahoo.com")).rstrip("/")
        network = config.get("_network", {})
        self.client = HttpClient(
            user_agent=str(network.get("user_agent", "personal-financial-terminal/0.1")),
            timeout=float(network.get("timeout_seconds", 10)),
            retries=int(network.get("retries", 2)),
        )
        self._crumb: str | None = None
        self._crumb_at = 0.0
        self._crumb_lock = threading.Lock()

    def snapshot(self, symbol: str) -> Fundamentals:
        result = self._quote_summary(
            symbol,
            ["price", "summaryDetail", "defaultKeyStatistics", "financialData", "assetProfile", "calendar"],
        )
        price = result.get("price") or {}
        detail = result.get("summaryDetail") or {}
        stats = result.get("defaultKeyStatistics") or {}
        financial = result.get("financialData") or {}
        profile = result.get("assetProfile") or {}
        calendar = result.get("calendar") or {}

        fields: dict[str, float | None] = {}
        pairs = {
            "price": price.get("regularMarketPrice"),
            "previous_close": price.get("regularMarketPreviousClose") or detail.get("previousClose"),
            "market_cap": price.get("regularMarketCap"),
            "volume": price.get("regularMarketVolume"),
            "average_volume": detail.get("averageDailyVolume10Day"),
            "fifty_two_week_high": detail.get("fiftyTwoWeekHigh"),
            "fifty_two_week_low": detail.get("fiftyTwoWeekLow"),
            "trailing_pe": stats.get("trailingPE") or detail.get("trailingPE"),
            "forward_pe": stats.get("forwardPE"),
            "peg_ratio": stats.get("trailingPegRatio") or stats.get("pegRatio"),
            "price_to_sales": stats.get("priceToSalesTrailing12Months"),
            "price_to_book": stats.get("priceToBook"),
            "enterprise_value": stats.get("enterpriseValue"),
            "ev_to_ebitda": stats.get("enterpriseToEbitda"),
            "ev_to_revenue": stats.get("enterpriseToRevenue"),
            "beta": detail.get("beta") or stats.get("beta"),
            "dividend_yield": detail.get("dividendYield"),
            "dividend_rate": detail.get("dividendRate"),
            "payout_ratio": detail.get("payoutRatio"),
            "eps_trailing": stats.get("trailingEps"),
            "eps_forward": stats.get("forwardEps"),
            "book_value": stats.get("bookValue"),
            "shares_outstanding": stats.get("sharesOutstanding"),
            "revenue": financial.get("totalRevenue"),
            "revenue_growth": financial.get("revenueGrowth"),
            "earnings_growth": financial.get("earningsGrowth"),
            "gross_profit": financial.get("grossProfits"),
            "ebitda": financial.get("ebitda"),
            "free_cash_flow": financial.get("freeCashflow"),
            "operating_cash_flow": financial.get("operatingCashflow"),
            "profit_margin": financial.get("profitMargins"),
            "operating_margin": financial.get("operatingMargins"),
            "gross_margin": financial.get("grossMargins"),
            "ebitda_margin": financial.get("ebitdaMargins"),
            "roe": financial.get("returnOnEquity"),
            "roa": financial.get("returnOnAssets"),
            "current_ratio": financial.get("currentRatio"),
            "quick_ratio": financial.get("quickRatio"),
            "total_debt": financial.get("totalDebt"),
            "total_cash": financial.get("totalCash"),
            "target_mean_price": financial.get("targetMeanPrice"),
            "analyst_count": financial.get("numberOfAnalystOpinions"),
            "recommendation": financial.get("recommendationMean"),
            "cash_to_debt": financial.get("cashToDebt"),
            "debt_to_equity": (
                _raw(financial.get("debtToEquity")) / 100.0
                if _raw(financial.get("debtToEquity")) is not None
                else None
            ),
        }
        for key, value in pairs.items():
            fields[key] = _raw(value)

        text_fields = {
            "name": str(price.get("longName") or price.get("shortName") or ""),
            "currency": str(price.get("currency") or ""),
            "exchange": str(price.get("fullExchangeName") or price.get("exchangeName") or ""),
            "quote_type": str(price.get("quoteType") or ""),
            "sector": str(profile.get("sector") or ""),
            "industry": str(profile.get("industry") or ""),
            "website": str(profile.get("website") or ""),
            "employees": str(profile.get("fullTimeEmployees") or ""),
            "summary": str(profile.get("longBusinessSummary") or "")[:800],
            "next_earnings": _earnings_date(calendar),
        }
        return Fundamentals(
            symbol=symbol,
            currency=text_fields["currency"],
            fields=fields,
            text_fields=text_fields,
            source=self.name,
            fetched_at=utcnow_iso(),
        )

    def statements(self, symbol: str, period: str = "annual") -> Statements:
        prefix = "annual" if period.lower().startswith("ann") else "quarterly"
        types = [prefix + suffix for suffix in STATEMENT_TYPES.values()]
        now = int(time.time())
        data = self.client.get_json(
            f"{self.base_url}/ws/fundamentals-timeseries/v1/finance/timeseries/{symbol}",
            params={
                "symbol": symbol,
                "type": ",".join(types),
                "period1": 631152000,
                "period2": now + 31_536_000,
            },
        )
        results = (data.get("timeseries") or {}).get("result") or []
        if not results:
            raise ProviderError(f"no statements for {symbol}")
        buckets: dict[str, dict[str, float | None]] = {}
        currency = ""
        for entry in results:
            meta = entry.get("meta") or {}
            type_names = meta.get("type") or []
            if not type_names:
                continue
            type_name = type_names[0]
            suffix = type_name[len(prefix):] if type_name.startswith(prefix) else type_name
            field = REVERSE_STATEMENT_TYPES.get(suffix)
            if field is None:
                continue
            for observation in entry.get(type_name) or []:
                if not isinstance(observation, dict):
                    continue
                as_of = observation.get("asOfDate")
                if not as_of:
                    continue
                buckets.setdefault(as_of, {})[field] = _raw(observation.get("reportedValue"))
                currency = observation.get("currencyCode") or currency
        if not buckets:
            raise ProviderError(f"no statement periods for {symbol}")
        periods = [
            StatementPeriod(date=date, fields=fields)
            for date, fields in sorted(buckets.items(), reverse=True)
        ]
        return Statements(
            symbol=symbol,
            period="annual" if prefix == "annual" else "quarterly",
            currency=currency,
            periods=periods,
            source=self.name,
            fetched_at=utcnow_iso(),
        )

    def profile(self, symbol: str) -> SymbolInfo:
        result = self._quote_summary(symbol, ["price", "assetProfile"])
        price = result.get("price") or {}
        profile = result.get("assetProfile") or {}
        return SymbolInfo(
            symbol=price.get("symbol") or symbol,
            name=str(price.get("longName") or price.get("shortName") or ""),
            exchange=str(price.get("fullExchangeName") or ""),
            quote_type=str(price.get("quoteType") or ""),
            sector=str(profile.get("sector") or ""),
            industry=str(profile.get("industry") or ""),
            currency=str(price.get("currency") or ""),
            source=self.name,
        )

    def _quote_summary(self, symbol: str, modules: list[str]) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(2):
            crumb = self._get_crumb(refresh=attempt > 0)
            try:
                data = self.client.get_json(
                    f"{self.base_url}/v10/finance/quoteSummary/{symbol}",
                    params={"modules": ",".join(modules), "crumb": crumb},
                )
            except (ProviderUnavailable, ProviderError) as exc:
                last_error = exc
                if attempt == 0:
                    continue
                raise
            summary = data.get("quoteSummary") or {}
            error = summary.get("error")
            if error:
                description = str(error.get("description") or "")
                if "crumb" in description.lower() or "unauthorized" in description.lower():
                    last_error = ProviderError(description)
                    continue
                if "not found" in description.lower() or "does not exist" in description.lower():
                    raise SymbolNotFound(f"{symbol}: {description}")
                raise ProviderError(f"{symbol}: {description}")
            results = summary.get("result") or []
            if not results:
                raise SymbolNotFound(f"no fundamentals for {symbol}")
            return results[0]
        raise ProviderUnavailable(f"quoteSummary failed for {symbol}: {last_error}")

    def _get_crumb(self, refresh: bool = False) -> str:
        with self._crumb_lock:
            if not refresh and self._crumb and (time.time() - self._crumb_at) < 3600:
                return self._crumb
            try:
                self.client.session.get("https://fc.yahoo.com", timeout=5)
            except Exception:
                pass
            response = self.client.session.get(
                f"{self.base_url}/v1/test/getcrumb", timeout=self.client.timeout
            )
            crumb = (response.text or "").strip()
            if response.status_code != 200 or not crumb or "<" in crumb:
                raise ProviderUnavailable("could not obtain yahoo request crumb")
            self._crumb = crumb
            self._crumb_at = time.time()
            return crumb

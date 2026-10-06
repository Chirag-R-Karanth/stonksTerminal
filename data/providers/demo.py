from __future__ import annotations

import hashlib
import random
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from data.models import (
    Fundamentals,
    History,
    MacroObservation,
    MacroSeries,
    NewsItem,
    Quote,
    SymbolInfo,
)
from data.providers.base import (
    FundamentalDataProvider,
    MacroDataProvider,
    MarketDataProvider,
    NewsProvider,
    SymbolNotFound,
)
from database.sqlite_db import utcnow_iso

DEMO_UNIVERSE: dict[str, tuple[str, float, str]] = {
    "AAPL": ("Apple Inc.", 265.0, "NASDAQ"),
    "MSFT": ("Microsoft Corporation", 430.0, "NASDAQ"),
    "NVDA": ("NVIDIA Corporation", 178.0, "NASDAQ"),
    "GOOGL": ("Alphabet Inc. Class A", 210.0, "NASDAQ"),
    "GOOG": ("Alphabet Inc. Class C", 210.0, "NASDAQ"),
    "AMZN": ("Amazon.com Inc.", 235.0, "NASDAQ"),
    "META": ("Meta Platforms Inc.", 720.0, "NASDAQ"),
    "TSLA": ("Tesla Inc.", 340.0, "NASDAQ"),
    "JPM": ("JPMorgan Chase & Co.", 310.0, "NYSE"),
    "V": ("Visa Inc.", 360.0, "NYSE"),
    "JNJ": ("Johnson & Johnson", 185.0, "NYSE"),
    "WMT": ("Walmart Inc.", 105.0, "NYSE"),
    "PG": ("Procter & Gamble Co.", 175.0, "NYSE"),
    "XOM": ("Exxon Mobil Corporation", 135.0, "NYSE"),
    "HD": ("Home Depot Inc.", 420.0, "NYSE"),
    "KO": ("The Coca-Cola Company", 75.0, "NYSE"),
    "PEP": ("PepsiCo Inc.", 165.0, "NASDAQ"),
    "MRK": ("Merck & Co. Inc.", 115.0, "NYSE"),
    "ABBV": ("AbbVie Inc.", 225.0, "NYSE"),
    "COST": ("Costco Wholesale Corporation", 1050.0, "NASDAQ"),
    "AVGO": ("Broadcom Inc.", 430.0, "NASDAQ"),
    "AMD": ("Advanced Micro Devices Inc.", 185.0, "NASDAQ"),
    "NFLX": ("Netflix Inc.", 1250.0, "NASDAQ"),
    "CRM": ("Salesforce Inc.", 330.0, "NYSE"),
    "ORCL": ("Oracle Corporation", 315.0, "NYSE"),
    "INTC": ("Intel Corporation", 38.0, "NASDAQ"),
    "DIS": ("The Walt Disney Company", 130.0, "NYSE"),
    "NKE": ("NIKE Inc.", 95.0, "NYSE"),
    "CAT": ("Caterpillar Inc.", 520.0, "NYSE"),
    "BA": ("The Boeing Company", 240.0, "NYSE"),
    "GS": ("The Goldman Sachs Group Inc.", 720.0, "NYSE"),
    "TCS": ("Tata Consultancy Services", 4150.0, "NSE"),
    "INFY": ("Infosys Limited", 1890.0, "NSE"),
    "NIFTY": ("Nifty 50 Index", 26100.0, "NSE"),
    "TCS.NS": ("Tata Consultancy Services", 4150.0, "NSE"),
    "INFY.NS": ("Infosys Limited", 1890.0, "NSE"),
    "RELIANCE.NS": ("Reliance Industries Limited", 3100.0, "NSE"),
    "HDFCBANK.NS": ("HDFC Bank Limited", 1950.0, "NSE"),
    "ICICIBANK.NS": ("ICICI Bank Limited", 1450.0, "NSE"),
    "SBIN.NS": ("State Bank of India", 980.0, "NSE"),
    "LT.NS": ("Larsen & Toubro Limited", 4300.0, "NSE"),
    "ITC.NS": ("ITC Limited", 490.0, "NSE"),
    "BHARTIARTL.NS": ("Bharti Airtel Limited", 2650.0, "NSE"),
    "TATAMOTORS.NS": ("Tata Motors Limited", 1080.0, "NSE"),
    "^GSPC": ("S&P 500", 6850.0, "NYSE"),
    "^DJI": ("Dow Jones Industrial Average", 47500.0, "NYSE"),
    "^IXIC": ("Nasdaq Composite", 24500.0, "NASDAQ"),
    "^NSEI": ("NIFTY 50", 26100.0, "NSE"),
    "^BSESN": ("BSE SENSEX", 85500.0, "BSE"),
    "^FTSE": ("FTSE 100", 9450.0, "LSE"),
    "^GDAXI": ("DAX Performance Index", 25000.0, "XETRA"),
    "^N225": ("Nikkei 225", 52000.0, "TSE"),
    "BTC-USD": ("Bitcoin USD", 122000.0, "CCY"),
}


def _rng(symbol: str, tag: str) -> random.Random:
    seed = int(hashlib.sha256(f"{symbol}:{tag}".encode()).hexdigest()[:12], 16)
    return random.Random(seed)


def _is_demo_symbol(symbol: str) -> bool:
    return symbol in DEMO_UNIVERSE


class DemoMarketProvider(MarketDataProvider):
    name = "demo"
    is_demo = True

    def __init__(self, config: dict[str, Any] | None = None):
        self.config = config or {}

    def search(self, query: str, limit: int = 8) -> list[SymbolInfo]:
        needle = query.upper()
        out = []
        for symbol, (name, _, exchange) in DEMO_UNIVERSE.items():
            if needle in symbol or needle in name.upper():
                out.append(SymbolInfo(symbol=symbol, name=name, exchange=exchange, quote_type="EQUITY", source=self.name, is_demo=True))
            if len(out) >= limit:
                break
        return out

    def _meta(self, symbol: str) -> tuple[str, float, str]:
        if symbol not in DEMO_UNIVERSE:
            raise SymbolNotFound(f"demo universe has no symbol {symbol}")
        name, base, exchange = DEMO_UNIVERSE[symbol]
        return name, base, exchange

    def quote(self, symbol: str) -> Quote:
        name, base, exchange = self._meta(symbol)
        history = self.history(symbol, "5D")
        candles = history.candles
        price = candles[-1].close
        previous = candles[-2].close if len(candles) > 1 else price
        change = price - previous
        return Quote(
            symbol=symbol,
            price=price,
            currency="USD",
            previous_close=previous,
            change=change,
            change_pct=(change / previous * 100.0) if previous else None,
            open=candles[-1].open,
            day_high=candles[-1].high,
            day_low=candles[-1].low,
            volume=candles[-1].volume,
            fifty_two_high=base * 1.25,
            fifty_two_low=base * 0.72,
            market_time=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            source=self.name,
            is_demo=True,
            fetched_at=utcnow_iso(),
        )

    def history(self, symbol: str, period: str, interval: str | None = None) -> History:
        _, base, _ = self._meta(symbol)
        rng = _rng(symbol, period)
        days = {"INTRA": 1, "1D": 1, "5D": 5, "1M": 31, "3M": 93, "6M": 186, "1Y": 366, "2Y": 731, "5Y": 1827, "MAX": 3653}.get(period.upper(), 366)
        intraday = period.upper() in ("INTRA", "1D", "5D")
        points = []
        if intraday:
            steps = 78 if period.upper() in ("INTRA", "1D") else 78 * 5
            start = datetime.now(timezone.utc).replace(hour=9, minute=30, second=0, microsecond=0) - timedelta(days=min(days, 5))
            price = base * (1 + rng.uniform(-0.04, 0.02))
            for i in range(steps):
                price *= 1 + rng.gauss(0.0001, 0.0018)
                stamp = start + timedelta(minutes=15 * i)
                points.append((stamp.strftime("%Y-%m-%dT%H:%M"), price))
        else:
            start = datetime.now(timezone.utc) - timedelta(days=days)
            price = base * (1 - min(days, 3653) / 3653 * 0.18)
            step_days = 1 if period.upper() != "MAX" or days <= 3653 else 1
            cursor = start
            while cursor <= datetime.now(timezone.utc):
                if cursor.weekday() < 5:
                    price *= 1 + rng.gauss(0.0004, 0.011)
                    points.append((cursor.strftime("%Y-%m-%d"), price))
                cursor += timedelta(days=step_days)
        from data.models import Candle

        candles = []
        for stamp, close in points:
            open_ = close * (1 + rng.gauss(0, 0.002))
            high = max(open_, close) * (1 + abs(rng.gauss(0, 0.003)))
            low = min(open_, close) * (1 - abs(rng.gauss(0, 0.003)))
            candles.append(
                Candle(ts=stamp, open=round(open_, 4), high=round(high, 4), low=round(low, 4),
                       close=round(close, 4), volume=float(rng.randint(1_000_000, 80_000_000)))
            )
        return History(symbol=symbol, interval="intraday" if intraday else "1d", period=period.upper(),
                       currency="USD", candles=candles, source=self.name, is_demo=True, fetched_at=utcnow_iso())


class DemoFundamentalProvider(FundamentalDataProvider):
    name = "demo"
    is_demo = True

    def snapshot(self, symbol: str) -> Fundamentals:
        if symbol.upper() not in DEMO_UNIVERSE:
            raise SymbolNotFound(f"demo universe has no symbol {symbol}")
        rng = _rng(symbol, "fundamentals")
        revenue = round(rng.uniform(8e9, 400e9), 0)
        fields = {
            "price": None,
            "market_cap": round(revenue * rng.uniform(3.0, 12.0), 0),
            "trailing_pe": round(rng.uniform(12, 45), 2),
            "forward_pe": round(rng.uniform(10, 38), 2),
            "peg_ratio": round(rng.uniform(0.8, 3.0), 2),
            "price_to_sales": round(rng.uniform(1.0, 12.0), 2),
            "price_to_book": round(rng.uniform(1.0, 15.0), 2),
            "roe": round(rng.uniform(0.05, 0.65), 4),
            "revenue": revenue,
            "revenue_growth": round(rng.uniform(-0.05, 0.35), 4),
            "profit_margin": round(rng.uniform(0.03, 0.35), 4),
            "operating_margin": round(rng.uniform(0.05, 0.45), 4),
            "gross_margin": round(rng.uniform(0.2, 0.8), 4),
            "free_cash_flow": round(revenue * rng.uniform(0.05, 0.3), 0),
            "total_debt": round(revenue * rng.uniform(0.0, 1.2), 0),
            "total_cash": round(revenue * rng.uniform(0.02, 0.4), 0),
            "debt_to_equity": round(rng.uniform(0.0, 2.5), 3),
            "dividend_yield": round(rng.uniform(0.0, 0.04), 4),
            "eps_trailing": round(revenue * 0.12 / 1e9, 2),
            "shares_outstanding": round(revenue * 5 / 1e9, 2),
            "beta": round(rng.uniform(0.5, 1.7), 2),
        }
        return Fundamentals(symbol=symbol, currency="USD", fields=fields,
                            text_fields={"sector": "DEMO", "industry": "DEMO", "name": "DEMO DATA"},
                            source=self.name, fetched_at=utcnow_iso())

    def statements(self, symbol: str, period: str = "annual"):
        from data.models import StatementPeriod, Statements

        rng = _rng(symbol, f"statements:{period}")
        periods = []
        year = datetime.now(timezone.utc).year - 1
        revenue = 50e9
        for i in range(5):
            revenue *= 1 + rng.uniform(-0.05, 0.2)
            date = f"{year - i}-12-31"
            periods.append(StatementPeriod(date=date, fields={
                "revenue": round(revenue, 0),
                "net_income": round(revenue * rng.uniform(0.02, 0.3), 0),
                "gross_profit": round(revenue * rng.uniform(0.25, 0.7), 0),
                "free_cash_flow": round(revenue * rng.uniform(0.03, 0.25), 0),
                "operating_income": round(revenue * rng.uniform(0.05, 0.4), 0),
                "diluted_eps": round(revenue * 0.1 / 1e9, 2),
            }))
        return Statements(symbol=symbol, period="annual" if period.startswith("ann") else "quarterly",
                          currency="USD", periods=periods, source=self.name, fetched_at=utcnow_iso())

    def profile(self, symbol: str) -> SymbolInfo:
        name, _, exchange = DEMO_UNIVERSE.get(symbol, (symbol, 0, "DEMO"))
        return SymbolInfo(symbol=symbol, name=name, exchange=exchange, sector="DEMO", industry="DEMO",
                          source=self.name, is_demo=True)


class DemoNewsProvider(NewsProvider):
    name = "demo"
    is_demo = True

    def headlines(self, symbols=None, query=None, limit: int = 50) -> list[NewsItem]:
        now = datetime.now(timezone.utc)
        items = []
        for i in range(min(limit, 20)):
            stamp = now - timedelta(minutes=37 * i)
            items.append(NewsItem(
                id=f"demo-{i}",
                title=f"DEMO headline {i + 1} — sample data, not real news",
                summary="Demo provider output. Configure a real news provider for live headlines.",
                url="",
                published_at=stamp.isoformat(timespec="seconds"),
                source="DEMO",
                category="demo",
                symbols=list(symbols or []),
            ))
        return items


class DemoMacroProvider(MacroDataProvider):
    name = "demo"
    is_demo = True

    def series(self, series_id: str, limit: int = 800) -> MacroSeries:
        rng = _rng(series_id, "macro")
        today = datetime.now(timezone.utc).date()
        observations = []
        value = rng.uniform(50, 120)
        for i in range(min(limit, 360)):
            value *= 1 + rng.gauss(0.0005, 0.006)
            day = today - timedelta(days=30 * i)
            observations.append(MacroObservation(date=day.isoformat(), value=round(value, 3)))
        observations.reverse()
        return MacroSeries(id=series_id, title=f"{series_id} (DEMO)", units="demo units",
                           source=self.name, observations=observations, fetched_at=utcnow_iso())

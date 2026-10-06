from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar

T = TypeVar("T")

STATUS_LIVE = "live"
STATUS_CACHED = "cached"
STATUS_STALE = "stale"
STATUS_OFFLINE = "offline"
STATUS_ERROR = "error"
STATUS_DEMO = "demo"


@dataclass(frozen=True)
class Money:
    value: float
    currency: str = "USD"
    ts: str | None = None


@dataclass
class SymbolInfo:
    symbol: str
    name: str = ""
    exchange: str = ""
    quote_type: str = ""
    sector: str = ""
    industry: str = ""
    currency: str = ""
    source: str = ""
    is_demo: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "name": self.name,
            "exchange": self.exchange,
            "quote_type": self.quote_type,
            "sector": self.sector,
            "industry": self.industry,
            "currency": self.currency,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SymbolInfo":
        return cls(**{k: data.get(k, "") for k in (
            "symbol", "name", "exchange", "quote_type", "sector", "industry", "currency", "source"
        )})


@dataclass
class Quote:
    symbol: str
    price: float
    currency: str = ""
    previous_close: float | None = None
    change: float | None = None
    change_pct: float | None = None
    open: float | None = None
    day_high: float | None = None
    day_low: float | None = None
    volume: float | None = None
    average_volume: float | None = None
    fifty_two_high: float | None = None
    fifty_two_low: float | None = None
    market_cap: float | None = None
    market_time: str | None = None
    source: str = ""
    is_demo: bool = False
    fetched_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Quote":
        return cls(**data)


@dataclass
class Candle:
    ts: str
    open: float | None
    high: float | None
    low: float | None
    close: float
    volume: float | None = None


@dataclass
class History:
    symbol: str
    interval: str
    period: str
    currency: str = ""
    candles: list[Candle] = field(default_factory=list)
    source: str = ""
    is_demo: bool = False
    fetched_at: str = ""

    @property
    def closes(self) -> list[float]:
        return [c.close for c in self.candles]

    @property
    def dates(self) -> list[str]:
        return [c.ts for c in self.candles]


@dataclass
class Fundamentals:
    symbol: str
    currency: str = ""
    fields: dict[str, float | None] = field(default_factory=dict)
    text_fields: dict[str, str] = field(default_factory=dict)
    source: str = ""
    as_of: str | None = None
    fetched_at: str = ""

    def get(self, key: str, default: float | None = None) -> float | None:
        return self.fields.get(key, default)

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "currency": self.currency,
            "fields": self.fields,
            "text_fields": self.text_fields,
            "source": self.source,
            "as_of": self.as_of,
            "fetched_at": self.fetched_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Fundamentals":
        return cls(
            symbol=data.get("symbol", ""),
            currency=data.get("currency", ""),
            fields=dict(data.get("fields", {})),
            text_fields=dict(data.get("text_fields", {})),
            source=data.get("source", ""),
            as_of=data.get("as_of"),
            fetched_at=data.get("fetched_at", ""),
        )


@dataclass
class StatementPeriod:
    date: str
    fields: dict[str, float | None] = field(default_factory=dict)


@dataclass
class Statements:
    symbol: str
    period: str
    currency: str = ""
    periods: list[StatementPeriod] = field(default_factory=list)
    source: str = ""
    fetched_at: str = ""

    def series(self, key: str) -> list[tuple[str, float | None]]:
        return [(p.date, p.fields.get(key)) for p in self.periods]

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "period": self.period,
            "currency": self.currency,
            "periods": [{"date": p.date, "fields": p.fields} for p in self.periods],
            "source": self.source,
            "fetched_at": self.fetched_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Statements":
        return cls(
            symbol=data.get("symbol", ""),
            period=data.get("period", "annual"),
            currency=data.get("currency", ""),
            periods=[StatementPeriod(p["date"], dict(p.get("fields", {}))) for p in data.get("periods", [])],
            source=data.get("source", ""),
            fetched_at=data.get("fetched_at", ""),
        )


@dataclass
class NewsItem:
    id: str
    title: str
    summary: str = ""
    url: str = ""
    published_at: str | None = None
    source: str = ""
    category: str = ""
    symbols: list[str] = field(default_factory=list)


@dataclass
class MacroObservation:
    date: str
    value: float


@dataclass
class MacroSeries:
    id: str
    title: str
    units: str = ""
    currency: str = ""
    source: str = ""
    observations: list[MacroObservation] = field(default_factory=list)
    fetched_at: str = ""


@dataclass
class DataResult(Generic[T]):
    data: T | None = None
    status: str = STATUS_LIVE
    message: str = ""
    provider: str = ""
    fetched_at: str | None = None
    is_demo: bool = False

    @property
    def ok(self) -> bool:
        return self.data is not None

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from analytics.engine import AnalyticsEngine, AnalyticsError, AnalyticsUnavailable, AnalyticsTimeout

__all__ = [
    "Analytics",
    "PerformanceStats",
    "DcfResult",
    "AnalyticsError",
    "AnalyticsUnavailable",
    "AnalyticsTimeout",
]


@dataclass
class PerformanceStats:
    cagr: float | None = None
    volatility: float | None = None
    sharpe: float | None = None
    sortino: float | None = None
    max_drawdown: float | None = None
    calmar: float | None = None
    win_rate: float | None = None
    var: float | None = None
    cvar: float | None = None
    best_period: float | None = None
    worst_period: float | None = None
    total_return: float | None = None
    years: float | None = None
    observations: int | None = None
    skew: float | None = None
    kurtosis: float | None = None

    @classmethod
    def from_result(cls, result: dict[str, Any]) -> "PerformanceStats":
        fields = {k: result.get(k) for k in cls.__dataclass_fields__ if k in result}
        return cls(**fields)


@dataclass
class DcfResult:
    assumptions: dict[str, Any]
    base: dict[str, Any]
    bull: dict[str, Any]
    bear: dict[str, Any]
    upside_vs_price: float | None
    model: str = "dcf"

    @classmethod
    def from_result(cls, result: dict[str, Any]) -> "DcfResult":
        return cls(
            assumptions=result.get("assumptions", {}),
            base=result.get("base", {}),
            bull=result.get("bull", {}),
            bear=result.get("bear", {}),
            upside_vs_price=result.get("upside_vs_price"),
            model=str(result.get("model", "dcf")),
        )


class Analytics:
    def __init__(self, engine: AnalyticsEngine, risk_free: float = 0.04, periods_per_year: int = 252):
        self.engine = engine
        self.risk_free = risk_free
        self.periods_per_year = periods_per_year

    @property
    def available(self) -> bool:
        return self.engine.available

    def performance(self, prices: Sequence[float], dates: Sequence[str] | None = None) -> PerformanceStats:
        result = self.engine.call(
            "performance",
            {
                "prices": list(prices),
                "dates": list(dates) if dates else None,
                "risk_free": self.risk_free,
                "periods_per_year": self.periods_per_year,
            },
        )
        return PerformanceStats.from_result(result or {})

    def equity_curve(self, prices: Sequence[float]) -> list[float]:
        result = self.engine.call("equity_curve", {"prices": list(prices)})
        return list((result or {}).get("values", []))

    def drawdowns(self, prices: Sequence[float]) -> list[float]:
        result = self.engine.call("drawdown_series", {"prices": list(prices)})
        return list((result or {}).get("values", []))

    def xirr(self, flows: Sequence[tuple[str, float]]) -> float:
        result = self.engine.call(
            "xirr",
            {"dates": [f[0] for f in flows], "amounts": [f[1] for f in flows]},
        )
        if isinstance(result, dict):
            result = result.get("value")
        if result is None:
            raise AnalyticsError("xirr returned no value")
        return float(result)

    def indicator(self, name: str, values: Sequence[float], window: int = 20, **extra: Any) -> list[float]:
        params = {"values": list(values), "window": window}
        params.update(extra)
        result = self.engine.call(name, params)
        return list((result or {}).get("values", []))

    def macd(self, values: Sequence[float], fast: int = 12, slow: int = 26, signal: int = 9) -> dict[str, list[float]]:
        result = self.engine.call("macd", {"values": list(values), "fast": fast, "slow": slow, "signal": signal})
        result = result or {}
        return {
            "macd": list(result.get("macd", [])),
            "signal": list(result.get("signal", [])),
            "histogram": list(result.get("histogram", [])),
        }

    def bollinger(self, values: Sequence[float], window: int = 20, deviations: float = 2.0) -> dict[str, list[float]]:
        result = self.engine.call(
            "bollinger", {"values": list(values), "window": window, "deviations": deviations}
        )
        result = result or {}
        return {k: list(result.get(k, [])) for k in ("upper", "mid", "lower", "width")}

    def vwap(self, high: Sequence[float], low: Sequence[float], close: Sequence[float], volume: Sequence[float]) -> list[float]:
        result = self.engine.call(
            "vwap", {"high": list(high), "low": list(low), "close": list(close), "volume": list(volume)}
        )
        return list((result or {}).get("values", []))

    def atr(self, high: Sequence[float], low: Sequence[float], close: Sequence[float], window: int = 14) -> list[float]:
        result = self.engine.call(
            "atr", {"high": list(high), "low": list(low), "close": list(close), "window": window}
        )
        return list((result or {}).get("values", []))

    def multiples(self, fundamentals: dict[str, float | None], price: float | None = None) -> dict[str, float | None]:
        params = dict(fundamentals)
        if price is not None:
            params["price"] = price
        return dict(self.engine.call("multiples", params) or {})

    def dcf(self, **assumptions: Any) -> DcfResult:
        return DcfResult.from_result(self.engine.call("dcf", assumptions) or {})

    def portfolio_stats(
        self,
        symbols: Sequence[str],
        weights: Sequence[float],
        returns: dict[str, Sequence[float]],
        bench_returns: Sequence[float] | None = None,
        alpha: float = 0.05,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "symbols": list(symbols),
            "weights": list(weights),
            "returns": {s: list(returns[s]) for s in symbols},
            "risk_free": self.risk_free,
            "periods_per_year": self.periods_per_year,
            "alpha": alpha,
        }
        if bench_returns is not None:
            params["bench_returns"] = list(bench_returns)
        return dict(self.engine.call("portfolio_stats", params) or {})

    def beta_alpha(self, returns: Sequence[float], bench_returns: Sequence[float]) -> dict[str, Any]:
        return dict(
            self.engine.call(
                "beta_alpha",
                {
                    "returns": list(returns),
                    "bench_returns": list(bench_returns),
                    "periods_per_year": self.periods_per_year,
                },
            )
            or {}
        )

    def correlation(self, symbols: Sequence[str], returns: dict[str, Sequence[float]]) -> dict[str, Any]:
        return dict(
            self.engine.call(
                "correlation", {"symbols": list(symbols), "returns": {s: list(returns[s]) for s in symbols}}
            )
            or {}
        )

    def regression(self, y: Sequence[float], x: dict[str, Sequence[float]]) -> dict[str, Any]:
        return dict(self.engine.call("regression", {"y": list(y), "x": x}) or {})

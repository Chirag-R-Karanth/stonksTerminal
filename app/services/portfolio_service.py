from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any

import pandas as pd

from analytics.api import Analytics, PerformanceStats
from app.config import Config
from app.services.market_service import MarketService
from data.models import DataResult, History
from database.repositories import PortfolioRepo, SymbolMetaRepo

log = logging.getLogger(__name__)

MODEL_LABEL = "MODEL: current holdings at constant weights"
VALID_SIDES = ("BUY", "SELL", "DIVIDEND", "DEPOSIT", "WITHDRAWAL")


class PortfolioService:
    def __init__(
        self,
        repo: PortfolioRepo,
        symbol_repo: SymbolMetaRepo,
        market: MarketService,
        analytics: Analytics,
        config: Config,
    ):
        self.repo = repo
        self.symbol_repo = symbol_repo
        self.market = market
        self.analytics = analytics
        self.config = config
        self.ensure()

    def ensure(self) -> None:
        self.repo.ensure_default(
            currency=str(self.config.get("portfolio.currency", "USD")),
            benchmark=str(self.config.get("analytics.default_benchmark", "^GSPC")),
        )

    def meta(self) -> dict[str, Any]:
        return self.repo.meta()

    def set_benchmark(self, symbol: str) -> None:
        self.repo.set_benchmark(symbol.upper())

    def add(
        self,
        side: str,
        symbol: str,
        quantity: float,
        price: float,
        trade_date: str | None = None,
        fees: float = 0.0,
        note: str | None = None,
    ) -> int:
        side = side.upper()
        if side not in VALID_SIDES:
            raise ValueError(f"invalid side {side}")
        if side in ("BUY", "SELL") and quantity <= 0:
            raise ValueError("quantity must be positive")
        self.market.resolve(symbol)
        when = trade_date or date.today().isoformat()
        return self.repo.add_transaction(
            symbol=symbol.upper(), side=side, quantity=abs(quantity), price=price,
            trade_date=when, fees=abs(fees), note=note,
        )

    def transactions(self, symbol: str | None = None) -> list[dict[str, Any]]:
        return self.repo.transactions(symbol=symbol)

    def delete_transaction(self, tx_id: int) -> bool:
        return self.repo.delete_transaction(tx_id)

    def holdings(self) -> list[dict[str, Any]]:
        return [h for h in self.repo.holdings() if h["quantity"] > 1e-9]

    def rows(self, force: bool = False) -> list[dict[str, Any]]:
        holdings = self.holdings()
        out: list[dict[str, Any]] = []
        for lot in holdings:
            symbol = lot["symbol"]
            meta = self.symbol_repo.get(symbol) or {}
            result = self.market.quote(symbol, force=force)
            quote = result.data
            qty = float(lot["quantity"])
            avg = (lot["cost"] / qty) if qty else 0.0
            price = quote.price if quote else None
            value = price * qty if price is not None else None
            unrealized = (price - avg) * qty if price is not None else None
            out.append(
                {
                    "symbol": symbol,
                    "name": meta.get("name") or "",
                    "sector": meta.get("sector") or "",
                    "quantity": qty,
                    "avg_cost": avg,
                    "price": price,
                    "change_pct": quote.change_pct if quote else None,
                    "value": value,
                    "unrealized": unrealized,
                    "realized": float(lot["realized"]),
                    "dividends": float(lot["dividends"]),
                    "currency": (quote.currency if quote else lot["currency"]),
                    "status": result.status,
                    "message": result.message or "",
                }
            )
        total = sum(r["value"] or 0.0 for r in out)
        for row in out:
            row["weight"] = (row["value"] / total) if total else None
        out.sort(key=lambda r: r["value"] or 0.0, reverse=True)
        return out

    def summary(self, force: bool = False) -> dict[str, Any]:
        rows = self.rows(force=force)
        market_value = sum(r["value"] or 0.0 for r in rows)
        cost = sum(r["avg_cost"] * r["quantity"] for r in rows)
        unrealized = sum(r["unrealized"] or 0.0 for r in rows)
        realized = sum(r["realized"] for r in rows)
        dividends = sum(r["dividends"] for r in rows)
        flows = self.repo.cash_flows()
        net_cash = sum(amount for _, amount in flows)
        day_change = sum(
            (r["change_pct"] or 0.0) / 100.0 * r["price"] * r["quantity"]
            for r in rows
            if r["price"] is not None and r["change_pct"] is not None
        )
        return {
            "holdings": len(rows),
            "market_value": market_value,
            "cost": cost,
            "unrealized": unrealized,
            "realized": realized,
            "dividends": dividends,
            "net_cash": net_cash,
            "day_change": day_change,
            "total_return": (unrealized + realized) / cost if cost else None,
            "rows": rows,
            "status": _worst_status(r["status"] for r in rows),
        }

    def allocation(self, force: bool = False) -> dict[str, Any]:
        rows = [r for r in self.rows(force=force) if r["value"]]
        total = sum(r["value"] or 0.0 for r in rows)
        by_symbol = {r["symbol"]: (r["value"] or 0.0) / total for r in rows} if total else {}
        by_sector: dict[str, float] = {}
        for row in rows:
            sector = row["sector"] or "Unknown"
            by_sector[sector] = by_sector.get(sector, 0.0) + (row["value"] or 0.0) / total
        return {"by_symbol": by_symbol, "by_sector": by_sector, "total": total}

    def xirr(self) -> float | None:
        flows = list(self.repo.cash_flows())
        if not flows:
            return None
        value = sum(r["value"] or 0.0 for r in self.rows())
        if value <= 0:
            return None
        flows.append((date.today().isoformat(), float(value)))
        amounts = [a for _, a in flows]
        if not (min(amounts) < 0 < max(amounts)):
            return None
        if not self.analytics.available:
            return None
        try:
            return self.analytics.xirr(flows)
        except Exception as exc:
            log.warning("xirr failed: %s", exc)
            return None

    def _returns_frame(self, period: str, force: bool = False) -> tuple[pd.DataFrame, dict[str, str]]:
        errors: dict[str, str] = {}
        closes: dict[str, pd.Series] = {}
        for lot in self.holdings():
            symbol = lot["symbol"]
            result = self.market.history(symbol, period, force=force)
            history = result.data
            if history is None or not history.candles:
                errors[symbol] = result.message or "no history"
                continue
            series = pd.Series(
                {pd.Timestamp(c.ts): c.close for c in history.candles},
                name=symbol,
                dtype=float,
            ).sort_index()
            series.index = series.index.tz_localize(None)
            closes[symbol] = series
        frame = pd.DataFrame(closes).sort_index()
        return frame, errors

    def _benchmark_series(self, period: str, frame: pd.DataFrame) -> pd.Series | None:
        benchmark = str(self.meta().get("benchmark") or "")
        if not benchmark or frame.empty:
            return None
        result = self.market.history(benchmark, period)
        history: History | None = result.data
        if history is None or not history.candles:
            return None
        series = pd.Series(
            {pd.Timestamp(c.ts): c.close for c in history.candles},
            name=benchmark,
            dtype=float,
        ).sort_index()
        series.index = series.index.tz_localize(None)
        return series.reindex(frame.index).ffill().bfill()

    def _weights(self, symbols: list[str]) -> dict[str, float]:
        rows = {r["symbol"]: r for r in self.rows() if r["value"] is not None}
        weights = {s: float(rows.get(s, {}).get("value") or 0.0) for s in symbols}
        total = sum(weights.values())
        if total <= 0:
            equal = 1.0 / len(symbols) if symbols else 0.0
            return {s: equal for s in symbols}
        return {s: w / total for s, w in weights.items()}

    def performance(self, period: str = "1Y", force: bool = False) -> DataResult[dict[str, Any]]:
        frame, errors = self._returns_frame(period, force=force)
        if frame.shape[1] == 0:
            return DataResult(
                data=None, status="error",
                message="; ".join(f"{k}: {v}" for k, v in errors.items()) or "no price data",
                provider=self.market.name,
            )
        returns = frame.pct_change().iloc[1:].fillna(0.0)
        weights = self._weights(list(frame.columns))
        w = pd.Series({s: weights.get(s, 0.0) for s in returns.columns})
        if w.sum() > 0:
            port_ret = (returns * w).sum(axis=1) / w.sum()
        else:
            port_ret = returns.mean(axis=1)
        equity = (1.0 + port_ret).cumprod()
        payload: dict[str, Any] = {
            "period": period,
            "model": MODEL_LABEL,
            "dates": [d.strftime("%Y-%m-%d") for d in equity.index],
            "equity": [round(float(v), 6) for v in equity.tolist()],
            "weights": {k: round(v, 6) for k, v in weights.items()},
            "symbols": list(frame.columns),
            "errors": errors,
            "stats": None,
            "benchmark": None,
            "beta_alpha": None,
        }
        if self.analytics.available:
            try:
                stats = self.analytics.performance(equity.tolist(), payload["dates"])
                payload["stats"] = stats.__dict__
            except Exception as exc:
                log.warning("portfolio performance stats failed: %s", exc)
        bench = self._benchmark_series(period, frame)
        if bench is not None:
            common = equity.index.intersection(bench.index)
            if len(common) > 10:
                bench_eq = (bench.loc[common] / float(bench.loc[common].iloc[0]))
                bench_payload: dict[str, Any] = {
                    "symbol": str(self.meta().get("benchmark")),
                    "dates": [d.strftime("%Y-%m-%d") for d in bench_eq.index],
                    "equity": [round(float(v), 6) for v in bench_eq.tolist()],
                    "stats": None,
                }
                if self.analytics.available:
                    try:
                        bstats = self.analytics.performance(bench_eq.tolist(), bench_payload["dates"])
                        bench_payload["stats"] = bstats.__dict__
                        aligned_port = port_ret.reindex(common).fillna(0.0)
                        aligned_bench = (bench.pct_change().reindex(common)).fillna(0.0)
                        payload["beta_alpha"] = self.analytics.beta_alpha(
                            aligned_port.tolist(), aligned_bench.tolist()
                        )
                    except Exception as exc:
                        log.warning("benchmark stats failed: %s", exc)
                payload["benchmark"] = bench_payload
        status = "live" if not errors else "stale"
        if errors and frame.shape[1] == 0:
            status = "error"
        return DataResult(
            data=payload, status=status,
            message="; ".join(f"{k}: {v}" for k, v in errors.items()) or None,
            provider=self.market.name,
        )

    def risk(self, period: str = "1Y", force: bool = False) -> DataResult[dict[str, Any]]:
        frame, errors = self._returns_frame(period, force=force)
        if frame.shape[1] == 0:
            return DataResult(
                data=None, status="error",
                message="; ".join(f"{k}: {v}" for k, v in errors.items()) or "no price data",
                provider=self.market.name,
            )
        returns = frame.pct_change().iloc[1:].fillna(0.0)
        weights = self._weights(list(frame.columns))
        symbols = [s for s in returns.columns]
        returns_map = {s: returns[s].tolist() for s in symbols}
        weight_list = [weights.get(s, 0.0) for s in symbols]
        bench_returns = None
        bench = self._benchmark_series(period, frame)
        if bench is not None:
            bench_ret = bench.pct_change()
            aligned = bench_ret.reindex(returns.index).fillna(0.0)
            bench_returns = aligned.tolist()
        payload: dict[str, Any] = {
            "period": period,
            "model": MODEL_LABEL,
            "symbols": symbols,
            "weights": {s: round(weights.get(s, 0.0), 6) for s in symbols},
            "concentration": {
                "max_weight": max(weight_list) if weight_list else 0.0,
                "hhi": sum(w * w for w in weight_list),
                "count": len(symbols),
            },
            "sector_weights": self.allocation(force=force)["by_sector"],
            "stats": None,
            "errors": errors,
        }
        if self.analytics.available:
            try:
                stats = self.analytics.portfolio_stats(
                    symbols, weight_list, returns_map, bench_returns
                )
                payload["stats"] = stats
            except Exception as exc:
                log.warning("portfolio stats failed: %s", exc)
                payload["stats_error"] = str(exc)
        status = "live" if not errors else "stale"
        return DataResult(
            data=payload, status=status,
            message="; ".join(f"{k}: {v}" for k, v in errors.items()) or None,
            provider=self.market.name,
        )


def _worst_status(statuses: Any) -> str:
    order = ["live", "cached", "stale", "demo", "offline", "error"]
    worst = "live"
    for status in statuses:
        if status in order and order.index(status) > order.index(worst):
            worst = status
    if worst == "live":
        statuses = list(statuses)
        if not statuses:
            return "cached"
    return worst

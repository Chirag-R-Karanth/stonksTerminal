from __future__ import annotations

import json
import logging
from typing import Any, Callable, Iterable

import pandas as pd

from app.services.security_service import SecurityService
from app.services.watchlist_service import WatchlistService
from data.models import STATUS_CACHED, STATUS_ERROR, STATUS_LIVE, DataResult
from database.duck import AnalyticStore
from database.repositories import ScreenRepo, SymbolMetaRepo, WatchlistRepo
from database.sqlite_db import Database

log = logging.getLogger(__name__)

FILTER_FIELDS: dict[str, str] = {
    "PE": "trailing_pe",
    "FPE": "forward_pe",
    "FORWARDPE": "forward_pe",
    "PB": "price_to_book",
    "PRICEBOOK": "price_to_book",
    "PS": "price_to_sales",
    "PSSALES": "price_to_sales",
    "EVEBITDA": "ev_ebitda",
    "EVREVENUE": "ev_to_revenue",
    "EV": "enterprise_value",
    "ROE": "roe",
    "ROA": "roa",
    "MARGIN": "profit_margin",
    "NETMARGIN": "profit_margin",
    "PROFITMARGIN": "profit_margin",
    "GROSSMARGIN": "gross_margin",
    "OPMARGIN": "operating_margin",
    "EBITDAMARGIN": "ebitda_margin",
    "DEBTEQUITY": "debt_to_equity",
    "DE": "debt_to_equity",
    "DIVYIELD": "dividend_yield",
    "PAYOUT": "payout_ratio",
    "GROWTH": "revenue_growth",
    "REVENUEGROWTH": "revenue_growth",
    "EARNINGSGROWTH": "earnings_growth",
    "MARKETCAP": "market_cap",
    "MCAP": "market_cap",
    "FCF": "free_cash_flow",
    "OCF": "operating_cash_flow",
    "REVENUE": "revenue",
    "CASH": "total_cash",
    "DEBT": "total_debt",
    "BETA": "beta",
    "CURRENTRATIO": "current_ratio",
    "QUICKRATIO": "quick_ratio",
    "PEG": "peg_ratio",
    "EPSTRAILING": "eps_trailing",
    "EPSFORWARD": "eps_forward",
    "BOOKVALUE": "book_value",
    "PRICE": "price",
}

OUTPUT_COLUMNS = [
    "symbol", "name", "sector", "market_cap", "trailing_pe", "forward_pe",
    "price_to_book", "price_to_sales", "ev_ebitda", "roe", "profit_margin",
    "gross_margin", "debt_to_equity", "dividend_yield", "revenue_growth", "beta",
]

_OP_SQL = {"<": "<", "<=": "<=", ">": ">", ">=": ">=", "==": "=", "!=": "<>"}


def normalize_field(word: str) -> str | None:
    key = word.upper()
    for junk in (" ", "/", "-", "_", "."):
        key = key.replace(junk, "")
    if key in FILTER_FIELDS:
        return FILTER_FIELDS[key]
    return None


def filter_help() -> list[str]:
    return sorted(set(FILTER_FIELDS.keys()))


class ScreenerService:
    def __init__(
        self,
        db: Database,
        store: AnalyticStore,
        security: SecurityService,
        watchlists: WatchlistService,
        screens: ScreenRepo,
        symbol_repo: SymbolMetaRepo,
        watchlist_repo: WatchlistRepo,
        portfolio_symbols: Callable[[], Iterable[str]],
        config: Any,
    ):
        self.db = db
        self.store = store
        self.security = security
        self.watchlists = watchlists
        self.screens = screens
        self.symbol_repo = symbol_repo
        self.watchlist_repo = watchlist_repo
        self.portfolio_symbols = portfolio_symbols
        self.config = config
        self.max_fetch = int(config.get("screener.max_fetch", 60))

    def universe(self) -> list[str]:
        seen: dict[str, None] = {}
        for symbol in self.config.get("screener.universe", []) or []:
            seen[str(symbol).upper()] = None
        try:
            for symbol in self.watchlist_repo.all_symbols():
                seen[symbol.upper()] = None
        except Exception as exc:
            log.warning("watchlist universe failed: %s", exc)
        try:
            for symbol in self.portfolio_symbols():
                seen[symbol.upper()] = None
        except Exception as exc:
            log.warning("portfolio universe failed: %s", exc)
        return list(seen)

    def _cached_fundamentals(self) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        rows = self.db.query("SELECT key, payload FROM fundamentals_cache")
        for row in rows:
            try:
                payload = json.loads(row["payload"])
            except (TypeError, ValueError):
                continue
            out[str(row["key"]).upper()] = payload
        return out

    def ensure_fundamentals(
        self,
        symbols: list[str],
        cached: dict[str, dict[str, Any]],
        force: bool = False,
        progress: Callable[[int, int, str], None] | None = None,
    ) -> tuple[int, int]:
        missing = [s for s in symbols if force or s not in cached]
        if not missing:
            return 0, 0
        todo = missing[: self.max_fetch]
        fetched = 0
        failed = 0
        for index, symbol in enumerate(todo, start=1):
            if progress:
                progress(index, len(todo), symbol)
            try:
                result = self.security.fundamentals(symbol, force=force)
                if result.data is not None:
                    fetched += 1
                    cached[symbol.upper()] = result.data.to_dict()
                else:
                    failed += 1
            except Exception as exc:
                failed += 1
                log.warning("screener fetch failed for %s: %s", symbol, exc)
        return fetched, failed

    def _build_frame(
        self, cached: dict[str, dict[str, Any]], symbols: list[str]
    ) -> pd.DataFrame:
        records: list[dict[str, Any]] = []
        wanted = set(symbols)
        for symbol, payload in cached.items():
            if wanted and symbol not in wanted:
                continue
            fields = payload.get("fields") or {}
            text = payload.get("text_fields") or {}
            meta = self.symbol_repo.get(symbol) or {}
            record: dict[str, Any] = {
                "symbol": symbol,
                "name": meta.get("name") or text.get("short_name") or text.get("long_name") or "",
                "sector": meta.get("sector") or text.get("sector") or "",
            }
            for column in set(FILTER_FIELDS.values()) | set(OUTPUT_COLUMNS):
                if column in ("symbol", "name", "sector"):
                    continue
                value = fields.get(column)
                if isinstance(value, (int, float)):
                    record[column] = float(value)
            records.append(record)
        frame = pd.DataFrame(records)
        if not frame.empty:
            frame = frame.sort_values("market_cap", ascending=False, na_position="last")
        return frame.reset_index(drop=True)

    def run(
        self,
        filters: list[dict[str, Any]],
        limit: int = 100,
        force: bool = False,
        fetch_missing: bool = True,
        progress: Callable[[int, int, str], None] | None = None,
    ) -> DataResult[list[dict[str, Any]]]:
        universe = self.universe()
        cached = self._cached_fundamentals()
        fetched = failed = 0
        if fetch_missing:
            fetched, failed = self.ensure_fundamentals(universe, cached, force=force, progress=progress)
        for f in filters:
            if normalize_field(str(f.get("field", ""))) is None:
                return DataResult(
                    data=None, status=STATUS_ERROR,
                    message=f"unknown filter field {f.get('field')!r}; see HELP SCREEN",
                )
        frame = self._build_frame(cached, set(universe))
        if frame.empty:
            return DataResult(
                data=None, status=STATUS_ERROR,
                message="no universe data; try SCREEN with network access",
            )
        self.store.register("screener_universe", frame)
        where: list[str] = []
        for f in filters:
            column = normalize_field(str(f["field"]))
            op = _OP_SQL.get(str(f["op"]))
            if column is None or op is None:
                return DataResult(
                    data=None, status=STATUS_ERROR,
                    message=f"invalid filter {f.get('raw', f)!r}",
                )
            if column not in frame.columns:
                return DataResult(
                    data=None, status=STATUS_ERROR,
                    message=f"field {f['field']} unavailable for universe",
                )
            where.append(f"{column} {op} {float(f['value'])!r}")
        columns = list(dict.fromkeys(OUTPUT_COLUMNS))
        for f in filters:
            column = normalize_field(str(f["field"]))
            if column and column not in columns:
                columns.append(column)
        columns = [c for c in columns if c in frame.columns]
        quoted = ", ".join(dict.fromkeys(columns))
        sql = f"SELECT {quoted} FROM screener_universe"
        if where:
            sql += " WHERE " + " AND ".join(where)
        order = "market_cap DESC NULLS LAST" if "market_cap" in frame.columns else "symbol"
        sql += f" ORDER BY {order} LIMIT {max(1, int(limit))}"
        try:
            rows_df = self.store.query(sql)
        except Exception as exc:
            log.warning("screener query failed: %s", exc)
            return DataResult(data=None, status=STATUS_ERROR, message=str(exc))
        rows = json.loads(rows_df.to_json(orient="records"))
        status = STATUS_LIVE if fetched else STATUS_CACHED
        message = None
        if failed:
            message = f"{failed} symbol(s) unavailable"
            if not rows:
                status = STATUS_ERROR
        return DataResult(
            data=rows, status=status, message=message, provider=self.security.provider.name,
        )

    def save(self, name: str, filters_text: str) -> None:
        self.screens.save(name.upper(), filters_text)

    def load(self, name: str) -> str | None:
        return self.screens.load(name.upper())

    def list(self) -> list[dict[str, Any]]:
        return self.screens.list()

    def delete(self, name: str) -> bool:
        return self.screens.delete(name.upper())

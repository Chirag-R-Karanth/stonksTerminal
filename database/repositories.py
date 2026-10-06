from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from database.sqlite_db import Database, parse_iso, utcnow_iso


def _age_seconds(fetched_at: str) -> float:
    ts = parse_iso(fetched_at)
    if ts is None:
        return float("inf")
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - ts).total_seconds()


class SettingsRepo:
    def __init__(self, db: Database):
        self.db = db

    def get(self, key: str, default: Any = None) -> Any:
        row = self.db.query_one("SELECT value FROM settings WHERE key = ?", (key,))
        if row is None:
            return default
        try:
            return json.loads(row["value"])
        except json.JSONDecodeError:
            return default

    def set(self, key: str, value: Any) -> None:
        self.db.execute(
            "INSERT INTO settings(key, value, updated_at) VALUES(?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            (key, json.dumps(value), utcnow_iso()),
        )

    def all(self) -> dict[str, Any]:
        return {row["key"]: json.loads(row["value"]) for row in self.db.query("SELECT * FROM settings")}


class HistoryRepo:
    def __init__(self, db: Database, limit: int = 500):
        self.db = db
        self.limit = limit

    def add(self, command: str) -> None:
        self.db.execute("INSERT INTO command_history(command, executed_at) VALUES(?,?)", (command, utcnow_iso()))
        self.db.execute(
            "DELETE FROM command_history WHERE id NOT IN "
            "(SELECT id FROM command_history ORDER BY id DESC LIMIT ?)",
            (self.limit,),
        )

    def recent(self, limit: int = 50) -> list[str]:
        rows = self.db.query(
            "SELECT command FROM command_history ORDER BY id DESC LIMIT ?", (limit,)
        )
        return [r["command"] for r in rows]

    def clear(self) -> None:
        self.db.execute("DELETE FROM command_history")


class WatchlistRepo:
    def __init__(self, db: Database):
        self.db = db

    def create(self, name: str) -> int:
        cur = self.db.execute("INSERT INTO watchlists(name, created_at) VALUES(?,?)", (name, utcnow_iso()))
        return int(cur.lastrowid)

    def delete(self, name: str) -> bool:
        row = self.db.query_one("SELECT id FROM watchlists WHERE name = ?", (name,))
        if row is None:
            return False
        self.db.execute("DELETE FROM watchlists WHERE id = ?", (row["id"],))
        return True

    def rename(self, old: str, new: str) -> bool:
        try:
            self.db.execute("UPDATE watchlists SET name = ? WHERE name = ?", (new, old))
            return True
        except Exception:
            return False

    def list_all(self) -> list[dict[str, Any]]:
        out = []
        for row in self.db.query("SELECT * FROM watchlists ORDER BY name"):
            items = self.db.query(
                "SELECT symbol FROM watchlist_items WHERE watchlist_id = ? ORDER BY position, symbol",
                (row["id"],),
            )
            out.append({"id": row["id"], "name": row["name"], "symbols": [i["symbol"] for i in items]})
        return out

    def get(self, name: str) -> dict[str, Any] | None:
        for wl in self.list_all():
            if wl["name"].lower() == name.lower():
                return wl
        return None

    def add(self, name: str, symbol: str) -> bool:
        wl = self.get(name)
        if wl is None:
            return False
        if symbol in wl["symbols"]:
            return False
        pos = len(wl["symbols"])
        self.db.execute(
            "INSERT OR IGNORE INTO watchlist_items(watchlist_id, symbol, position, added_at) VALUES(?,?,?,?)",
            (wl["id"], symbol, pos, utcnow_iso()),
        )
        return True

    def remove(self, name: str, symbol: str) -> bool:
        wl = self.get(name)
        if wl is None:
            return False
        cur = self.db.execute(
            "DELETE FROM watchlist_items WHERE watchlist_id = ? AND symbol = ?", (wl["id"], symbol)
        )
        return cur.rowcount > 0

    def all_symbols(self) -> list[str]:
        rows = self.db.query("SELECT DISTINCT symbol FROM watchlist_items ORDER BY symbol")
        return [r["symbol"] for r in rows]


class PortfolioRepo:
    def __init__(self, db: Database):
        self.db = db

    def ensure_default(self, currency: str = "USD", benchmark: str = "^GSPC") -> int:
        row = self.db.query_one("SELECT id FROM portfolios ORDER BY id LIMIT 1")
        if row:
            return int(row["id"])
        cur = self.db.execute(
            "INSERT INTO portfolios(name, base_currency, benchmark, created_at) VALUES(?,?,?,?)",
            ("MAIN", currency, benchmark, utcnow_iso()),
        )
        return int(cur.lastrowid)

    def meta(self, portfolio_id: int | None = None) -> dict[str, Any]:
        if portfolio_id is None:
            portfolio_id = self.ensure_default()
        row = self.db.query_one("SELECT * FROM portfolios WHERE id = ?", (portfolio_id,))
        return dict(row) if row else {}

    def set_benchmark(self, symbol: str, portfolio_id: int | None = None) -> None:
        portfolio_id = portfolio_id or self.ensure_default()
        self.db.execute("UPDATE portfolios SET benchmark = ? WHERE id = ?", (symbol, portfolio_id))

    def add_transaction(
        self,
        symbol: str,
        side: str,
        quantity: float,
        price: float,
        trade_date: str,
        currency: str = "USD",
        fees: float = 0.0,
        note: str | None = None,
        portfolio_id: int | None = None,
    ) -> int:
        portfolio_id = portfolio_id or self.ensure_default()
        cur = self.db.execute(
            "INSERT INTO transactions(portfolio_id, symbol, side, quantity, price, currency, trade_date, fees, note, created_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?)",
            (portfolio_id, symbol, side, quantity, price, currency, trade_date, fees, note, utcnow_iso()),
        )
        return int(cur.lastrowid)

    def transactions(self, portfolio_id: int | None = None, symbol: str | None = None) -> list[dict[str, Any]]:
        portfolio_id = portfolio_id or self.ensure_default()
        sql = "SELECT * FROM transactions WHERE portfolio_id = ?"
        params: list[Any] = [portfolio_id]
        if symbol:
            sql += " AND symbol = ?"
            params.append(symbol)
        sql += " ORDER BY trade_date, id"
        return [dict(r) for r in self.db.query(sql, tuple(params))]

    def delete_transaction(self, tx_id: int) -> bool:
        cur = self.db.execute("DELETE FROM transactions WHERE id = ?", (tx_id,))
        return cur.rowcount > 0

    def holdings(self, portfolio_id: int | None = None) -> list[dict[str, Any]]:
        lots: dict[str, dict[str, Any]] = {}
        for tx in self.transactions(portfolio_id):
            symbol = tx["symbol"]
            lot = lots.setdefault(
                symbol,
                {"symbol": symbol, "quantity": 0.0, "cost": 0.0, "realized": 0.0,
                 "cash_flow": 0.0, "currency": tx["currency"], "dividends": 0.0},
            )
            side, qty, price, fees = tx["side"], float(tx["quantity"]), float(tx["price"]), float(tx["fees"])
            if side == "BUY":
                lot["quantity"] += qty
                lot["cost"] += qty * price + fees
                lot["cash_flow"] += qty * price + fees
            elif side == "SELL":
                sold = min(qty, max(lot["quantity"], 0.0))
                avg = (lot["cost"] / lot["quantity"]) if lot["quantity"] > 0 else price
                lot["realized"] += sold * (price - avg) - fees
                lot["quantity"] -= qty
                lot["cost"] = avg * max(lot["quantity"], 0.0)
                lot["cash_flow"] -= qty * price - fees
            elif side == "DIVIDEND":
                lot["dividends"] += float(tx["price"])
                lot["cash_flow"] -= float(tx["price"])
            elif side == "DEPOSIT":
                lot["cash_flow"] -= qty * price
            elif side == "WITHDRAWAL":
                lot["cash_flow"] += qty * price
        return [lot for lot in lots.values() if abs(lot["quantity"]) > 1e-9 or lot["dividends"]]

    def cash_flows(self, portfolio_id: int | None = None) -> list[tuple[str, float]]:
        portfolio_id = portfolio_id or self.ensure_default()
        flows: dict[str, float] = {}
        for tx in self.transactions(portfolio_id):
            amount = 0.0
            if tx["side"] == "BUY":
                amount = -(float(tx["quantity"]) * float(tx["price"]) + float(tx["fees"]))
            elif tx["side"] == "SELL":
                amount = float(tx["quantity"]) * float(tx["price"]) - float(tx["fees"])
            elif tx["side"] == "DIVIDEND":
                amount = float(tx["price"])
            elif tx["side"] == "DEPOSIT":
                amount = float(tx["quantity"]) * float(tx["price"])
            elif tx["side"] == "WITHDRAWAL":
                amount = -float(tx["quantity"]) * float(tx["price"])
            flows[tx["trade_date"]] = flows.get(tx["trade_date"], 0.0) + amount
        return sorted(flows.items())


class ScreenRepo:
    def __init__(self, db: Database):
        self.db = db

    def save(self, name: str, query: str) -> None:
        now = utcnow_iso()
        self.db.execute(
            "INSERT INTO saved_screens(name, query, created_at, updated_at) VALUES(?,?,?,?) "
            "ON CONFLICT(name) DO UPDATE SET query=excluded.query, updated_at=excluded.updated_at",
            (name, query, now, now),
        )

    def load(self, name: str) -> str | None:
        row = self.db.query_one("SELECT query FROM saved_screens WHERE name = ?", (name,))
        return row["query"] if row else None

    def list(self) -> list[dict[str, Any]]:
        return [dict(r) for r in self.db.query("SELECT * FROM saved_screens ORDER BY name")]

    def delete(self, name: str) -> bool:
        cur = self.db.execute("DELETE FROM saved_screens WHERE name = ?", (name,))
        return cur.rowcount > 0


class SymbolMetaRepo:
    def __init__(self, db: Database):
        self.db = db

    def upsert(self, info: dict[str, Any]) -> None:
        self.db.execute(
            "INSERT INTO symbol_meta(symbol, name, exchange, quote_type, sector, industry, currency, source, updated_at) "
            "VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(symbol) DO UPDATE SET "
            "name=COALESCE(excluded.name, symbol_meta.name), "
            "exchange=COALESCE(excluded.exchange, symbol_meta.exchange), "
            "quote_type=COALESCE(excluded.quote_type, symbol_meta.quote_type), "
            "sector=COALESCE(excluded.sector, symbol_meta.sector), "
            "industry=COALESCE(excluded.industry, symbol_meta.industry), "
            "currency=COALESCE(excluded.currency, symbol_meta.currency), "
            "source=excluded.source, updated_at=excluded.updated_at",
            (
                info.get("symbol"), info.get("name"), info.get("exchange"), info.get("quote_type"),
                info.get("sector"), info.get("industry"), info.get("currency"),
                info.get("source"), utcnow_iso(),
            ),
        )

    def get(self, symbol: str) -> dict[str, Any] | None:
        row = self.db.query_one("SELECT * FROM symbol_meta WHERE symbol = ?", (symbol,))
        return dict(row) if row else None

    def search(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        like = f"%{query}%"
        rows = self.db.query(
            "SELECT * FROM symbol_meta WHERE symbol LIKE ? OR name LIKE ? "
            "ORDER BY CASE WHEN symbol LIKE ? THEN 0 ELSE 1 END, symbol LIMIT ?",
            (like, like, f"{query}%", limit),
        )
        return [dict(r) for r in rows]

    def all_symbols(self) -> list[str]:
        return [r["symbol"] for r in self.db.query("SELECT symbol FROM symbol_meta ORDER BY symbol")]


class FetchLogRepo:
    def __init__(self, db: Database):
        self.db = db

    def record(self, entity: str, data_type: str, provider: str, ok: bool, detail: str | None = None) -> None:
        self.db.execute(
            "INSERT INTO fetch_log(entity, data_type, provider, retrieved_at, ok, detail) VALUES(?,?,?,?,?,?)",
            (entity, data_type, provider, utcnow_iso(), 1 if ok else 0, detail),
        )

    def last_ok(self, entity: str, data_type: str) -> datetime | None:
        row = self.db.query_one(
            "SELECT retrieved_at FROM fetch_log WHERE entity = ? AND data_type = ? AND ok = 1 "
            "ORDER BY retrieved_at DESC LIMIT 1",
            (entity, data_type),
        )
        return parse_iso(row["retrieved_at"]) if row else None

    def prune(self, keep: int = 2000) -> None:
        self.db.execute(
            "DELETE FROM fetch_log WHERE id NOT IN (SELECT id FROM fetch_log ORDER BY id DESC LIMIT ?)",
            (keep,),
        )


class ProvenanceRepo:
    def __init__(self, db: Database):
        self.db = db

    def record(
        self,
        entity: str,
        field: str,
        data_type: str,
        provider: str,
        source: str,
        currency: str | None = None,
    ) -> None:
        self.db.execute(
            "INSERT INTO provenance(entity, field, data_type, provider, source, currency, retrieved_at) "
            "VALUES(?,?,?,?,?,?,?)",
            (entity, field, data_type, provider, source, currency, utcnow_iso()),
        )

    def latest(self, entity: str, data_type: str) -> dict[str, Any] | None:
        row = self.db.query_one(
            "SELECT * FROM provenance WHERE entity = ? AND data_type = ? "
            "ORDER BY retrieved_at DESC LIMIT 1",
            (entity, data_type),
        )
        return dict(row) if row else None


class JsonCacheRepo:
    def __init__(self, db: Database, table: str):
        self.db = db
        self.table = table

    def get(self, key: str) -> tuple[Any, str] | None:
        row = self.db.query_one(
            f"SELECT payload, fetched_at FROM {self.table} WHERE key = ?", (key,)
        )
        if row is None:
            return None
        return json.loads(row["payload"]), row["fetched_at"]

    def get_fresh(self, key: str, ttl_seconds: float) -> tuple[Any, str, bool] | None:
        entry = self.get(key)
        if entry is None:
            return None
        payload, fetched_at = entry
        return payload, fetched_at, _age_seconds(fetched_at) <= ttl_seconds

    def put(self, key: str, payload: Any, provider: str) -> str:
        now = utcnow_iso()
        self.db.execute(
            f"INSERT INTO {self.table}(key, payload, provider, fetched_at) VALUES(?,?,?,?) "
            f"ON CONFLICT(key) DO UPDATE SET payload=excluded.payload, provider=excluded.provider, "
            f"fetched_at=excluded.fetched_at",
            (key, json.dumps(payload), provider, now),
        )
        return now

    def keys(self) -> list[str]:
        return [r["key"] for r in self.db.query(f"SELECT key FROM {self.table}")]


class NewsCacheRepo:
    def __init__(self, db: Database):
        self.db = db

    def put_many(self, items: list[dict[str, Any]], provider: str) -> int:
        now = utcnow_iso()
        count = 0
        with self.db.transaction() as conn:
            for item in items:
                conn.execute(
                    "INSERT INTO news_cache(guid, title, summary, url, published_at, source, category, symbols, fetched_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(guid) DO UPDATE SET "
                    "title=excluded.title, summary=excluded.summary, published_at=excluded.published_at, "
                    "symbols=excluded.symbols, fetched_at=excluded.fetched_at",
                    (
                        item["id"], item["title"], item.get("summary"), item.get("url"),
                        item.get("published_at"), item.get("source"), item.get("category"),
                        json.dumps(item.get("symbols", [])), now,
                    ),
                )
                count += 1
        return count

    def list(
        self,
        limit: int = 200,
        query: str | None = None,
        symbols: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        rows = [dict(r) for r in self.db.query(
            "SELECT * FROM news_cache ORDER BY COALESCE(published_at, fetched_at) DESC LIMIT ?",
            (max(limit * 3, 300),),
        )]
        out = []
        for row in rows:
            row["symbols"] = json.loads(row["symbols"] or "[]")
            if symbols:
                tagged = {s.upper() for s in row["symbols"]}
                if not tagged.intersection({s.upper() for s in symbols}):
                    text = (row["title"] + " " + (row.get("summary") or "")).upper()
                    if not any(s.upper() in text for s in symbols):
                        continue
            if query:
                haystack = f"{row['title']} {row.get('summary') or ''} {row.get('source') or ''}".lower()
                if query.lower() not in haystack:
                    continue
            out.append(row)
            if len(out) >= limit:
                break
        return out

    def prune(self, keep: int = 2000) -> None:
        self.db.execute(
            "DELETE FROM news_cache WHERE guid NOT IN "
            "(SELECT guid FROM news_cache ORDER BY COALESCE(published_at, fetched_at) DESC LIMIT ?)",
            (keep,),
        )

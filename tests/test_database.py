import pandas as pd
import pytest

from database.duck import AnalyticStore
from database.repositories import (
    HistoryRepo,
    NewsCacheRepo,
    PortfolioRepo,
    ScreenRepo,
    SettingsRepo,
    SymbolMetaRepo,
    WatchlistRepo,
)
from database.sqlite_db import Database, utcnow_iso


@pytest.fixture()
def db(tmp_path):
    database = Database(tmp_path / "test.db")
    database.migrate()
    yield database
    database.close()


def test_migrate_is_idempotent_and_versioned(db, tmp_path):
    files = db.migration_files()
    assert files
    assert db.user_version() == max(version for version, _ in files)
    assert db.migrate() == []
    assert db.verify()


def test_fresh_database_has_expected_tables(db):
    names = {row["name"] for row in db.query("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {
        "settings", "command_history", "watchlists", "watchlist_items",
        "transactions", "saved_screens", "symbol_meta", "news_cache",
    } <= names


def test_settings_roundtrip(db):
    repo = SettingsRepo(db)
    assert repo.get("missing", "fallback") == "fallback"
    repo.set("a.b", {"x": 1})
    assert repo.get("a.b") == {"x": 1}
    repo.set("a.b", [1, 2, 3])
    assert repo.get("a.b") == [1, 2, 3]
    assert "a.b" in repo.all()


def test_history_recent_is_desc(db):
    repo = HistoryRepo(db, limit=3)
    for i in range(5):
        repo.add(f"CMD{i}")
    recent = repo.recent(10)
    assert recent == ["CMD4", "CMD3", "CMD2"]
    repo.clear()
    assert repo.recent() == []


def test_watchlist_lifecycle(db):
    repo = WatchlistRepo(db)
    repo.create("core")
    assert repo.add("core", "AAPL") is True
    assert repo.add("core", "AAPL") is False
    repo.add("core", "MSFT")
    got = repo.get("core")
    assert got["symbols"] == ["AAPL", "MSFT"]
    assert repo.remove("core", "AAPL") is True
    assert "MSFT" in repo.all_symbols()
    assert [w["name"] for w in repo.list_all()] == ["core"]
    assert repo.delete("core") is True
    assert repo.get("core") is None


def test_portfolio_transactions_and_holdings(db):
    repo = PortfolioRepo(db)
    tx_id = repo.add_transaction("AAPL", "BUY", 10, 250, "2026-01-05")
    repo.add_transaction("AAPL", "SELL", 4, 260, "2026-02-01")
    repo.add_transaction("MSFT", "BUY", 5, 400, "2026-01-06")
    txs = repo.transactions()
    assert len(txs) == 3
    assert any(t["id"] == tx_id for t in txs)
    holdings = {row["symbol"]: row for row in repo.holdings()}
    assert holdings["AAPL"]["quantity"] == pytest.approx(6)
    assert holdings["MSFT"]["quantity"] == pytest.approx(5)
    assert repo.meta()["benchmark"]
    repo.set_benchmark("QQQ")
    assert repo.meta()["benchmark"] == "QQQ"
    assert repo.delete_transaction(tx_id) is True
    assert len(repo.transactions()) == 2
    flows = repo.cash_flows()
    assert flows and any(amount < 0 for _, amount in flows)


def test_screen_repo_roundtrip(db):
    repo = ScreenRepo(db)
    repo.save("cheap", "PE<20")
    assert repo.load("cheap") == "PE<20"
    assert {row["name"] for row in repo.list()} == {"cheap"}
    assert repo.delete("cheap") is True
    assert repo.load("cheap") is None


def test_symbol_meta_upsert(db):
    repo = SymbolMetaRepo(db)
    repo.upsert({"symbol": "AAPL", "name": "Apple Inc.", "exchange": "NASDAQ", "sector": "Technology"})
    row = repo.get("AAPL")
    assert row["name"] == "Apple Inc."
    repo.upsert({"symbol": "AAPL", "name": "Apple", "exchange": "NASDAQ", "sector": "Technology"})
    assert repo.get("AAPL")["name"] == "Apple"
    assert "AAPL" in repo.all_symbols()
    assert repo.search("app")[0]["symbol"] == "AAPL"


def test_news_cache_roundtrip(db):
    repo = NewsCacheRepo(db)
    count = repo.put_many(
        [
            {
                "id": "abc",
                "title": "Headline one",
                "summary": "summary",
                "url": "https://example.com/1",
                "published_at": "2026-01-01T10:00:00+00:00",
                "source": "feed",
                "category": "general",
                "symbols": ["AAPL"],
            }
        ],
        provider="test",
    )
    assert count == 1
    rows = repo.list(limit=10)
    assert rows[0]["title"] == "Headline one"
    assert repo.list(limit=10, symbols=["MSFT"]) == []
    assert repo.list(limit=10, query="Headline")
    repo.prune(keep=0)
    assert repo.list() == []


def test_json_cache_freshness(db):
    from database.repositories import JsonCacheRepo

    repo = JsonCacheRepo(db, "quote_cache")
    fetched = repo.put("AAPL", {"price": 1}, "test")
    assert fetched
    fresh = repo.get_fresh("AAPL", ttl_seconds=3600)
    assert fresh is not None and fresh[2] is True
    stale = repo.get_fresh("AAPL", ttl_seconds=-1)
    assert stale is not None and stale[2] is False


def test_analytic_store_roundtrip(tmp_path):
    store = AnalyticStore(tmp_path / "parquet", tmp_path / "analytics.duckdb")
    frame = pd.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]})
    store.register("t_df", frame)
    out = store.query("SELECT a FROM t_df WHERE a > 1")
    assert out["a"].tolist() == [2, 3]

    prices = pd.DataFrame(
        {
            "ts": [1, 2, 3],
            "open": [10.0, 11.0, 12.0],
            "high": [11.0, 12.0, 13.0],
            "low": [9.0, 10.0, 11.0],
            "close": [10.5, 11.5, 12.5],
            "volume": [100, 200, 300],
        }
    )
    store.write_prices("TEST", prices, "1d")
    read = store.read_prices("TEST", interval="1d")
    assert len(read) == 3
    store.write_prices("TEST", prices, "1d")
    assert len(store.read_prices("TEST", interval="1d")) == 3
    matrix = store.price_matrix(["TEST"])
    assert not matrix.empty
    store.close()


def test_fetch_log(db):
    from database.repositories import FetchLogRepo

    repo = FetchLogRepo(db)
    repo.record("AAPL", "quote", "test", True)
    assert repo.last_ok("AAPL", "quote") is not None
    repo.prune(keep=0)
    assert repo.last_ok("AAPL", "quote") is None
    assert utcnow_iso()

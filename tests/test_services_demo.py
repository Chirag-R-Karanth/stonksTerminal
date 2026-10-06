import pytest
from data.providers.base import SymbolNotFound
from data.models import STATUS_LIVE


def test_market_quote_demo(demo_state):
    result = demo_state.market.quote("AAPL")
    assert result.ok
    assert result.data.price > 0
    assert result.data.symbol == "AAPL"
    assert result.is_demo or result.provider == "demo"


def test_market_history_demo(demo_state):
    result = demo_state.market.history("AAPL", "1Y")
    assert result.ok
    assert len(result.data.candles) > 100
    assert result.data.candles[0].close > 0


def test_resolve_and_search(demo_state):
    info = demo_state.market.resolve("aapl")
    assert info.symbol == "AAPL"
    hits = demo_state.market.search("apple")
    assert any(h.symbol == "AAPL" for h in hits)
    local = demo_state.market.search_local("AA")
    assert any(h.symbol == "AAPL" for h in local)
    with pytest.raises(SymbolNotFound):
        demo_state.market.resolve("ZZZZZZZ")


def test_unknown_history_is_error_result(demo_state):
    result = demo_state.market.history("ZZZZZZZ", "1Y")
    assert not result.ok
    assert result.message


def test_news_rows(demo_state):
    result = demo_state.news.rows(limit=5)
    assert result.ok
    assert 0 < len(result.data) <= 5
    row = result.data[0]
    for key in ("title", "url", "source", "time"):
        assert key in row


def test_macro_catalog_and_series(demo_state):
    catalog = demo_state.macro.catalog()
    assert len(catalog) >= 8
    keys = {entry["key"] for entry in catalog}
    assert "US_DGS10" in keys
    result = demo_state.macro.series("US_DGS10")
    assert result.ok
    assert len(result.data.observations) >= 20
    latest = demo_state.macro.latest(result.data)
    assert latest is not None and isinstance(latest[1], float)
    overview = demo_state.macro.overview()
    assert set(overview) == keys


def test_yield_curve(demo_state):
    result = demo_state.macro.yield_curve()
    assert result.ok, result.message
    points = result.data["points"]
    assert len(points) >= 2
    assert points == sorted(points, key=lambda p: p["tenor"])
    assert all(isinstance(p["value"], float) for p in points)


def test_watchlist_service(demo_state):
    svc = demo_state.watchlists
    name = svc.ensure()
    assert svc.add(name, "AAPL")
    assert svc.add(name, "MSFT")
    rows = svc.rows()
    symbols = {row["symbol"] for row in rows}
    assert {"AAPL", "MSFT"} <= symbols
    assert "AAPL" in {row["symbol"] for row in svc.rows()}
    assert name in svc.names()
    svc.remove(name, "MSFT")
    assert {row["symbol"] for row in svc.rows()} == {"AAPL"}
    other = "growth"
    assert svc.create(other)
    assert other in svc.names()
    svc.set_active(other)
    assert svc.rows() == []
    svc.delete(other)
    svc.set_active(name)


def test_portfolio_service(demo_state):
    svc = demo_state.portfolio
    svc.add("BUY", "AAPL", 10, 250, "2026-01-05")
    svc.add("BUY", "MSFT", 5, 400, "2026-01-06")
    rows = svc.rows()
    assert {row["symbol"] for row in rows} == {"AAPL", "MSFT"}
    aapl = next(r for r in rows if r["symbol"] == "AAPL")
    assert aapl["quantity"] == pytest.approx(10)
    assert aapl["value"] and aapl["value"] > 0

    summary = svc.summary()
    assert summary["holdings"] == 2
    assert summary["market_value"] > 0
    assert summary["status"] in {"live", "cached", "stale", "demo", "error"}

    allocation = svc.allocation()
    assert allocation["total"] > 0
    assert abs(sum(allocation["by_symbol"].values()) - 1.0) < 1e-6

    performance = svc.performance(period="1Y")
    assert performance.ok, performance.message
    data = performance.data
    assert data["model"].startswith("MODEL:")
    assert len(data["equity"]) > 10
    if demo_state.r_available:
        assert data["stats"] is not None
        assert "sharpe" in data["stats"]

    risk = svc.risk(period="1Y")
    assert risk.ok, risk.message
    assert risk.data["model"].startswith("MODEL:")
    assert {"AAPL", "MSFT"} <= set(risk.data["symbols"])
    if demo_state.r_available:
        assert risk.data["stats"] is not None
        assert risk.data["stats"]["volatility"] > 0


def test_security_service(demo_state):
    svc = demo_state.security
    fund = svc.fundamentals("AAPL")
    assert fund.ok
    assert fund.data.fields["trailing_pe"] > 0

    statements = svc.statements("AAPL", "annual")
    assert statements.ok
    assert len(statements.data.periods) >= 3

    profile = svc.profile("AAPL")
    assert profile.symbol == "AAPL"

    peers = svc.peers("AAPL")
    assert "MSFT" in peers

    valuation = svc.valuation("AAPL")
    assert valuation.ok
    if demo_state.r_available:
        multiples = valuation.data.get("multiples") or {}
        assert multiples

    model = svc.dcf_model("AAPL")
    assert model.ok, model.message
    assert model.data["assumptions"]["wacc"] > 0
    dcf = model.data["model"]
    if hasattr(dcf, "base"):
        assert dcf.base["intrinsic_value"] > 0

    missing = svc.fundamentals("ZZZZZZZ")
    assert not missing.ok


def test_screener_service(demo_state):
    from app.services.screener_service import filter_help, normalize_field

    assert normalize_field("PE") == "trailing_pe"
    assert normalize_field("debt/equity") == "debt_to_equity"
    assert normalize_field("DE") == "debt_to_equity"
    assert normalize_field("MARKETCAP") == "market_cap"
    assert normalize_field("nonsense") is None
    assert filter_help()

    svc = demo_state.screener
    universe = svc.universe()
    assert len(universe) >= 40

    result = svc.run(
        [{"field": "PE", "op": "<", "value": 100.0, "raw": "PE<100"}],
        limit=10,
    )
    assert result.ok, result.message
    rows = result.data
    assert 0 < len(rows) <= 10
    assert "symbol" in rows[0]
    assert all(row["trailing_pe"] is None or row["trailing_pe"] < 100 for row in rows)

    bad = svc.run([{"field": "NOPE", "op": "<", "value": 1.0, "raw": "NOPE<1"}])
    assert not bad.ok
    assert "unknown filter field" in (bad.message or "")

    svc.save("cheap", "PE<20")
    assert svc.load("cheap") == "PE<20"
    assert any(entry["name"] == "CHEAP" for entry in svc.list())
    assert svc.delete("cheap") is True


def test_screener_universe_includes_watchlist(demo_state):
    demo_state.watchlists.add(demo_state.watchlists.ensure(), "GOOG")
    universe = demo_state.screener.universe()
    assert "GOOG" in universe

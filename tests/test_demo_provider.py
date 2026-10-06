import pytest

from data.providers.base import SymbolNotFound
from data.providers.demo import DEMO_UNIVERSE, DemoFundamentalProvider
from app.services.screener_service import normalize_field


def test_demo_universe_covers_screener_universe():
    from app.config import Config

    config = Config.load()
    universe = [str(s) for s in config.get("screener.universe", [])]
    for symbol in universe:
        assert symbol in DEMO_UNIVERSE


def test_all_indices_present():
    for index in ("^GSPC", "^DJI", "^IXIC", "^NSEI", "^BSESN", "^FTSE", "^GDAXI", "^N225"):
        assert index in DEMO_UNIVERSE


def test_snapshot_deterministic():
    provider = DemoFundamentalProvider()
    first = provider.snapshot("AAPL")
    second = provider.snapshot("AAPL")
    assert first.fields == second.fields
    assert first.fields["trailing_pe"] > 0
    assert first.fields["market_cap"] > 0


def test_snapshot_unknown_raises():
    provider = DemoFundamentalProvider()
    with pytest.raises(SymbolNotFound):
        provider.snapshot("NOPE123")


def test_fundamentals_values_are_usable_ratios():
    provider = DemoFundamentalProvider()
    fields = provider.snapshot("MSFT").fields
    assert 0 < fields["roe"] <= 1
    assert 0 < fields["gross_margin"] <= 1
    assert fields["dividend_yield"] >= 0 and fields["dividend_yield"] < 1
    assert fields["debt_to_equity"] >= 0


def test_search_matches_name_and_symbol():
    from data.providers.demo import DemoMarketProvider

    provider = DemoMarketProvider()
    hits = provider.search("Alphabet", limit=50)
    assert any(h.symbol == "GOOGL" for h in hits)
    assert any(h.symbol == "GOOG" for h in provider.search("GOOG", limit=50))


def test_quote_live_fields():
    from data.providers.demo import DemoMarketProvider

    provider = DemoMarketProvider()
    quote = provider.quote("AAPL")
    assert quote.symbol == "AAPL"
    assert quote.price > 0
    assert quote.currency == "USD"
    assert quote.source == "demo"


def test_filter_field_cross_check():
    assert normalize_field("PE") == "trailing_pe"
    assert normalize_field("ev/ebitda") == "ev_ebitda"
    assert normalize_field("DE") == "debt_to_equity"
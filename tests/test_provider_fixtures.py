import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
sys.path.insert(0, str(Path(__file__).parent.parent))


class FakeClient:
    def __init__(self, payload):
        self.payload = payload

    def get_json(self, url, **kwargs):
        return self.payload


def test_raw_helper():
    from data.providers.market.yahoo import _raw

    assert _raw(None) is None
    assert _raw({"raw": "12.5", "fmt": "12.50"}) == 12.5
    assert _raw("42") == 42.0
    assert _raw(float("nan")) is None
    assert _raw("garbage") is None


def test_iso_helper():
    from data.providers.market.yahoo import _iso

    assert _iso(1736208000, "1d") == "2025-01-07"
    stamp = _iso(1736208000, "5m")
    assert stamp.startswith("2025-01-07T")
    assert len(stamp) == 16


def to_epoch_utc(year, month, day):
    from datetime import datetime, timezone

    return int(datetime(year, month, day, tzinfo=timezone.utc).timestamp())


def test_history_parses_fixture():
    from data.providers.market.yahoo import YahooMarketProvider

    payload = json.loads((FIXTURES / "yahoo_chart.json").read_text())
    provider = YahooMarketProvider({"base_url": "https://query1.finance.yahoo.com"})
    provider.client = FakeClient(payload)
    history = provider.history("AAPL", "1M")
    assert history.symbol == "AAPL"
    assert history.interval == "1d"
    assert history.period == "1M"
    assert len(history.candles) == 3
    assert history.candles[0].close == pytest.approx(243.9)
    assert history.candles[2].close == pytest.approx(248.0)
    assert history.candles[2].high == pytest.approx(253.0)
    assert history.candles[0].volume == pytest.approx(48000000)
    assert history.candles[0].ts.endswith("2025-01-07")
    assert history.candles[1].ts == "2025-01-08"
    assert history.currency == "USD"


def test_history_error_payload_raises_symbol_not_found():
    from data.providers.base import SymbolNotFound
    from data.providers.market.yahoo import YahooMarketProvider

    payload = {
        "chart": {
            "result": [],
            "error": {"code": "Not Found", "description": "No data found, symbol may be delisted"},
        }
    }
    provider = YahooMarketProvider({"base_url": "https://query1.finance.yahoo.com"})
    provider.client = FakeClient(payload)
    with pytest.raises(SymbolNotFound):
        provider.history("ZZZZ", "1Y")


def test_history_empty_timestamps_raises():
    from data.providers.base import ProviderError
    from data.providers.market.yahoo import YahooMarketProvider

    payload = {"chart": {"result": [{"timestamp": [], "indicators": {"quote": [{}]}, "meta": {}}], "error": None}}
    provider = YahooMarketProvider({"base_url": "https://query1.finance.yahoo.com"})
    provider.client = FakeClient(payload)
    with pytest.raises(ProviderError):
        provider.history("AAPL", "1Y")


def _fixture_bytes(name):
    return (FIXTURES / name).read_bytes()


def test_rss_parse_date():
    from data.providers.news.rss import _parse_date

    assert _parse_date("Mon, 05 Jan 2026 10:00:00 GMT") == "2026-01-05T10:00:00+00:00"
    assert _parse_date("2026-01-05T10:00:00Z") == "2026-01-05T10:00:00+00:00"
    assert _parse_date("garbage") is None
    assert _parse_date(None) is None


def test_rss_strip_html():
    from data.providers.news.rss import _strip_html

    assert _strip_html("<p>Apple <b>AAPL</b> rose</p>") == "Apple  AAPL  rose"


def test_rss_tag_symbols():
    from data.providers.news.rss import RssNewsProvider

    tagged = RssNewsProvider._tag_symbols("Apple AAPL shares, MSFT falls, THE GDP outlook")
    assert "AAPL" in tagged and "MSFT" in tagged
    assert "THE" not in tagged and "GDP" not in tagged
    assert RssNewsProvider._tag_symbols("plain text") == []


def test_rss_dedupe_by_id():
    from data.providers.news.rss import RssNewsProvider
    from data.models import NewsItem

    items = [
        NewsItem(id="a", title="one", summary="", url="x", published_at=None, source="s", category="g"),
        NewsItem(id="a", title="one dup", summary="", url="x", published_at=None, source="s", category="g"),
        NewsItem(id="b", title="two", summary="", url="y", published_at=None, source="s", category="g"),
    ]
    got = RssNewsProvider._dedupe(items)
    assert len(got) == 2


def test_rss_feed_parses_items():
    from data.providers.news.rss import RssNewsProvider

    provider = RssNewsProvider({"feeds": []})
    provider.client = SimpleNamespace(
        get=lambda url: SimpleNamespace(status_code=200, content=_fixture_bytes("rss_sample.xml"))
    )
    items = provider._feed_news(
        {"url": "https://example.com/rss", "name": "Market Wire", "category": "general"}
    )
    assert len(items) == 2
    first = items[0]
    assert first.title == "Apple announces new chip"
    assert "Apple  AAPL  unveiled" in first.summary
    assert first.url == "https://example.com/stories/apple-chip"
    assert first.published_at == "2026-01-05T10:00:00+00:00"
    assert first.category == "general"
    assert "AAPL" in first.symbols
    second = items[1]
    assert "MSFT" in second.symbols
    assert "GDP" not in second.symbols


def test_rss_feed_http_error():
    from data.providers.base import ProviderError
    from data.providers.news.rss import RssNewsProvider

    provider = RssNewsProvider({"feeds": []})
    provider.client = SimpleNamespace(get=lambda url: SimpleNamespace(status_code=500, content=b""))
    with pytest.raises(ProviderError):
        provider._feed_news({"url": "https://example.com/rss"})


def test_rss_feed_parse_error():
    from data.providers.base import ProviderError
    from data.providers.news.rss import RssNewsProvider

    provider = RssNewsProvider({"feeds": []})
    provider.client = SimpleNamespace(
        get=lambda url: SimpleNamespace(status_code=200, content=b"<broken")
    )
    with pytest.raises(ProviderError):
        provider._feed_news({"url": "https://example.com/rss"})
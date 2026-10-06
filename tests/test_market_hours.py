from dataclasses import replace
from datetime import datetime, timezone

import pytest

from app.config import Config
from data.market_hours import (
    exchange_for_symbol,
    load_sessions,
    local_clock,
    session_status,
    symbol_session_status,
)


@pytest.fixture(scope="module")
def config():
    return Config.load()


@pytest.fixture(scope="module")
def sessions(config):
    loaded = load_sessions(config)
    assert loaded, "default config must define trading sessions"
    return loaded


def test_sessions_defined(sessions):
    exchanges = {s.exchange for s in sessions}
    assert {"NYSE", "NSE"} <= exchanges
    for session in sessions:
        assert session.timezone
        assert session.open < session.close


def test_weekend(sessions):
    sunday = datetime(2026, 1, 4, 15, 0, tzinfo=timezone.utc)
    for session in sessions:
        assert session_status(session, sunday) == "WEEKEND"


def test_new_york_open_and_closed(sessions):
    nyse = next(s for s in sessions if s.exchange == "NYSE")
    monday_open = datetime(2026, 1, 5, 15, 0, tzinfo=timezone.utc)
    assert session_status(nyse, monday_open) == "OPEN"
    before_open = datetime(2026, 1, 5, 8, 0, tzinfo=timezone.utc)
    assert session_status(nyse, before_open) == "CLOSED"
    pre_market = datetime(2026, 1, 5, 14, 0, tzinfo=timezone.utc)
    assert session_status(nyse, pre_market) == "PRE-MARKET"
    after_hours = datetime(2026, 1, 5, 22, 0, tzinfo=timezone.utc)
    assert session_status(nyse, after_hours) == "AFTER-HOURS"


def test_india_closed_at_utc_midday(sessions):
    nse = next(s for s in sessions if s.exchange == "NSE")
    evening_india = datetime(2026, 1, 5, 15, 0, tzinfo=timezone.utc)
    assert session_status(nse, evening_india) == "CLOSED"
    india_open = datetime(2026, 1, 5, 5, 0, tzinfo=timezone.utc)
    assert session_status(nse, india_open) == "OPEN"


def test_holiday(sessions):
    nyse = next(s for s in sessions if s.exchange == "NYSE")
    holiday = replace(nyse, holidays=("2026-01-05",))
    assert session_status(holiday, datetime(2026, 1, 5, 15, 0, tzinfo=timezone.utc)) == "CLOSED"


def test_local_clock_format(sessions):
    nyse = next(s for s in sessions if s.exchange == "NYSE")
    clock = local_clock(nyse, datetime(2026, 1, 5, 15, 0, tzinfo=timezone.utc))
    assert clock == "10:00:00"


def test_exchange_mapping():
    assert exchange_for_symbol("RELIANCE.NS") == "NSE"
    assert exchange_for_symbol("^NSEI") == "NSE"
    assert exchange_for_symbol("^BSESN") == "BSE"
    assert exchange_for_symbol("TCS.BO") == "BSE"
    assert exchange_for_symbol("AAPL") == "NYSE"
    assert exchange_for_symbol("^GSPC") == "NYSE"


def test_symbol_session_status(sessions):
    assert symbol_session_status("RELIANCE.NS", sessions) in {"OPEN", "CLOSED", "PRE-MARKET", "AFTER-HOURS", "WEEKEND"}
    assert symbol_session_status("UNKNOWN.XX", sessions) in {"OPEN", "CLOSED", "PRE-MARKET", "AFTER-HOURS", "WEEKEND"}

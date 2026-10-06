import pytest

from app.ui import format


def test_num():
    assert format.num(None) == "—"
    assert format.num(1234.5678) == "1,234.57"
    assert format.num("abc") == "abc"


def test_int_num():
    assert format.int_num(None) == "—"
    assert format.int_num(1234.5) == "1,234"


def test_compact():
    assert format.compact(None) == "—"
    assert format.compact(1.5e9) == "1.50B"
    assert format.compact(-2.5e6) == "-2.50M"
    assert format.compact(500) == "500.00"


def test_pct_signed():
    assert format.pct(None) == "—"
    assert format.pct(0.1234) == "+12.34%"
    assert format.pct(-0.05) == "-5.00%"


def test_pct_abs():
    assert format.pct_abs(None) == "—"
    assert format.pct_abs(0.1) == "10.00%"


def test_sign_class():
    assert format.sign_class(0.05) == "ft-up"
    assert format.sign_class(-0.05) == "ft-down"
    assert format.sign_class(0) == "ft-dim"
    assert format.sign_class(None) == "ft-dim"
    assert format.sign_class(1, invert=True) == "ft-down"


def test_money():
    assert format.money(10, "USD") == "$10.00"
    assert format.money(10, "EUR") == "10.00 EUR"
    assert format.money(None) == "—"


def test_iso_date():
    assert format.iso_date(0) == "1970-01-01"
    assert format.iso_date(1735689600) == "2025-01-01"
    assert format.iso_date("not-a-number") == "not-a-number"


def test_status_bits_shape():
    bits = format.status_bits("live", "yahoo", "2026-01-01T00:00:00+00:00")
    assert bits
    assert all(isinstance(text, str) and isinstance(css, str) for text, css in bits)
    assert any("LIVE" in text for text, _ in bits)


def test_age_na():
    assert format.age(None) == "—"

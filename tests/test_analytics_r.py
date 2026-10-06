import math
from importlib import import_module

import pytest

from analytics.api import AnalyticsError


@pytest.fixture(scope="module")
def api() -> "object":
    return import_module("analytics.api")


def test_performance_manual_match(r_analytics, api):
    prices = [100.0, 104.0, 102.0, 108.0, 112.0]
    dates = ["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04", "2026-01-05"]
    stats = r_analytics.performance(prices, dates)
    assert isinstance(stats, api.PerformanceStats)
    assert stats.observations == len(prices) - 1
    assert stats.total_return == pytest.approx(0.12, rel=1e-6)
    assert stats.max_drawdown == pytest.approx(-0.019230769230769232, rel=1e-6)
    assert stats.win_rate == pytest.approx(0.75, rel=1e-6)
    assert stats.volatility > 0
    assert stats.cagr is not None and stats.cagr > 0
    assert math.isfinite(stats.sharpe)
    assert math.isfinite(stats.calmar)


def test_performance_without_dates(r_analytics):
    stats = r_analytics.performance([100.0, 110.0, 108.0, 115.0])
    assert stats.total_return == pytest.approx(0.15, rel=1e-6)


def test_equity_curve_and_drawdowns(r_analytics):
    prices = [100.0, 90.0, 95.0, 110.0]
    equity = r_analytics.equity_curve(prices)
    assert len(equity) >= len(prices) - 1
    dd = r_analytics.drawdowns(prices)
    assert len(dd) >= len(prices) - 1
    assert all(x <= 0 for x in dd)


def test_xirr(r_analytics):
    flows = [("2020-01-01", -1000.0), ("2021-01-01", 1100.0)]
    rate = r_analytics.xirr(flows)
    assert rate == pytest.approx(0.0996, rel=0.02)


def test_xirr_invalid_flows_error(r_analytics):
    with pytest.raises((AnalyticsError, RuntimeError, ValueError)):
        r_analytics.xirr([("2020-01-01", -100.0), ("2021-01-02", -50.0)])


def _clean(values):
    return [None if (v is None or (isinstance(v, float) and math.isnan(v))) else v for v in values]


def test_indicators_sma(r_analytics):
    values = r_analytics.indicator("sma", list(range(1, 11)), window=3)
    assert len(values) == 10
    assert _clean(values)[-1] == pytest.approx(9.0)
    assert _clean(values)[0] is None


def test_indicators_rsi_bounded(r_analytics):
    saw = []
    value = 100.0
    for _ in range(60):
        saw.append(value)
        value *= 1.01
    out = _clean(r_analytics.indicator("rsi", saw, window=14))
    last = [v for v in out if v is not None][-1]
    assert 0.0 <= last <= 100.0


def test_indicators_macd(r_analytics):
    saw = []
    value = 100.0
    for _ in range(80):
        saw.append(value)
        value *= 1.005
    bands = r_analytics.macd(saw, fast=12, slow=26, signal=9)
    assert set(bands) == {"macd", "signal", "histogram"}
    assert len(bands["macd"]) == 80
    tail = _clean(bands["macd"])
    assert tail[-1] > 0


def test_indicators_bollinger(r_analytics):
    values = [100.0 + math.sin(i / 4.0) * 5 for i in range(60)]
    bands = r_analytics.bollinger(values, window=20)
    assert set(bands) == {"upper", "mid", "lower", "width"}
    for key in ("upper", "mid", "lower"):
        assert len(bands[key]) == 60
    _u, _m, lo = [_clean(bands[k]) for k in ("upper", "mid", "lower")]
    assert lo[-1] is not None


def test_indicators_vwap_and_atr(r_analytics):
    high = [51.0] * 10
    low = [49.0] * 10
    close = [50.0] * 10
    volume = [1000.0] * 10
    vwap = _clean(r_analytics.vwap(high, low, close, volume))
    assert vwap[-1] == pytest.approx(50.0, abs=0.5)
    atr = _clean(r_analytics.atr(high, low, close, window=5))
    assert atr[-1] is not None and 0 < atr[-1] < 5


def test_multiples(r_analytics):
    multiples = r_analytics.multiples(
        {
            "shares": 1e9,
            "market_cap": 100e9,
            "revenue": 50e9,
            "net_income": 10e9,
            "ebitda": 15e9,
            "total_debt": 0.0,
            "cash": 0.0,
        },
        price=100.0,
    )
    assert multiples["pe"] == pytest.approx(10.0, rel=0.05)
    assert multiples["price_to_sales"] == pytest.approx(2.0, rel=0.05)
    assert multiples["ev_to_ebitda"] == pytest.approx(100.0 / 15.0, rel=0.05)


def test_dcf_scenarios_ordered(r_analytics, api):
    model = r_analytics.dcf(
        revenue=1000.0,
        shares=100.0,
        growth=0.06,
        ebit_margin=0.2,
        wacc=0.10,
        terminal_growth=0.03,
        tax_rate=0.2,
        capex_pct=0.05,
        nwc_pct=0.0,
        da_pct=0.0,
        net_debt=0.0,
        price=20.0,
        years=5,
    )
    assert isinstance(model, api.DcfResult)
    assert model.bear["intrinsic_value"] < model.base["intrinsic_value"] < model.bull["intrinsic_value"]
    assert model.base["intrinsic_value"] > 0
    assert model.base["equity_value"] > 0
    assert "wacc" in model.assumptions


def test_correlation(r_analytics):
    x = [100.0, 102.0, 99.0, 105.0, 103.0]
    out = r_analytics.correlation(["X", "Y"], {"X": x, "Y": x})
    assert out["symbols"] == ["X", "Y"]
    assert out["matrix"][0][1] == pytest.approx(1.0, abs=1e-3)
    assert out["matrix"][1][0] == pytest.approx(1.0, abs=1e-3)


def test_beta_alpha(r_analytics):
    x = [0.01, 0.02, 0.015, 0.025, 0.02, 0.018, 0.022, 0.013]
    y = [1.5 * v + 0.001 for v in x]
    out = r_analytics.beta_alpha(y, x)
    assert out["beta"] == pytest.approx(1.5, rel=1e-6)
    assert out["r_squared"] == pytest.approx(1.0, abs=1e-6)
    assert out["alpha_annualized"] == pytest.approx(0.252, rel=1e-6)


def test_portfolio_stats(r_analytics):
    symbol_returns = {
        "A": [0.01, -0.005, 0.02, 0.015, -0.01],
        "B": [0.02, 0.0, 0.03, 0.025, 0.005],
        "C": [0.0, 0.01, -0.01, 0.02, 0.03],
    }
    weights = [0.5, 0.3, 0.2]
    out = r_analytics.portfolio_stats(["A", "B", "C"], weights, symbol_returns)
    assert out["concentration_hhi"] == pytest.approx(0.38, rel=1e-3)
    assert set(out["risk_contributions"]) == {"A", "B", "C"}
    assert all(isinstance(v, (int, float)) for v in out["risk_contributions"].values())
    assert out["volatility_from_weights"] > 0
    assert len(out["correlation_matrix"]) == 3
    assert out["max_weight"] == pytest.approx(0.5, abs=1e-3)


def test_regression(r_analytics):
    x = [100.0 + i for i in range(10)]
    y = [2.0 * v + 5.0 for v in x]
    out = r_analytics.regression(y, {"x": x})
    assert out["r_squared"] == pytest.approx(1.0, abs=1e-9)
    coeffs = {row["term"]: row["estimate"] for row in out["coefficients"]}
    assert coeffs["(Intercept)"] == pytest.approx(5.0, rel=1e-6)
    assert coeffs["x"] == pytest.approx(2.0, rel=1e-6)


def test_equity_curve_commutative(r_analytics):
    stats = r_analytics.performance([100.0, 105.0, 103.0])
    assert stats.total_return == pytest.approx(0.03, rel=1e-6)
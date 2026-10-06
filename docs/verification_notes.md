# Verification Notes

## Environment (Fedora 43)

- Python 3.14.7 in a venv created with `--system-site-packages` to reuse the
  system PyGObject -> GTK 4.20.
- R 4.5.3 with `jsonlite`, `zoo`, `xts` installed under
  `~/.local/share/R/library`. `analytics/engine.py` adds those paths via
  `FT_R_LIBS`/`.libPaths` automatically.
- No sudo: system packages cannot be installed; `pip install` of cffi/curl
  headers is avoided by using the system build already linked against GTK.

## Verified working

- `terminal --check` reports R available, migrations applied, providers
  registered, and a 40-symbol screener universe.
- Full GUI smoke on `DISPLAY=:0`: 23 commands ran without a single traceback
  (watchlist, portfolio add/benchmark/risk/perf/history, chart, valuation,
  fundamentals, screener, macro, markets, compare, news, help, status,
  error paths). Screenshots archived under `/tmp/opencode/shot_*.png`.
- `pytest`: 125 tests pass (see below).

## R analytics layer

Per-op key contract (used by Python `analytics.api` and the views):

- `op_performance` returns `observations, mean_return_annualized, volatility,
  sharpe, sortino, max_drawdown, win_rate, var, cvar, best_period, worst_period,
  skew, kurtosis` plus `years, cagr, total_return, calmar`.
- `op_multiples` returns `pe, earnings_per_share, price_to_sales, price_to_book,
  ev_to_ebitda, ev_to_sales, ev_to_fcf, dividend_yield, roe, roic, gross_margin,
  operating_margin, net_margin, fcf_margin, debt_to_equity, market_cap,
  enterprise_value, tax_rate_used`.
- `op_dcf` returns `assumptions` (growth is a vector), `bear`, `base`, `bull`
  scenarios (each with `equity_value` and `intrinsic_value`), and top-level
  `upside_vs_price`.
- `op_portfolio_stats` nests a `benchmark` block with `beta, alpha_annualized,
  tracking_error, information_ratio, correlation` (note: the key is
  `alpha_annualized`, not `alpha`).
- Indicators return `values`, except `macd` (`macd/signal/histogram`) and
  `bollinger` (`upper/mid/lower/width`).
- `Analytics.performance(prices, dates)` expects dates as ISO strings; numeric
  epochs break R `as.Date`. Chart X-labels therefore always come as ISO dates.

## Known quirks handled in code

- Yahoo `dividendYield`, ROE, and margins return fractions; only
  `debtToEquity` is already percent-like (divided by 100).
- Yahoo chart payloads carry `error` blocks instead of empty results; those
  map to `SymbolNotFound`/`ProviderError`.
- DuckDB `read_parquet(..., filename=true)` is required to expose the source
  filename column used by `AnalyticStore.price_matrix`.
- Session status falls back to `NYSE` for unknown exchanges; `^NSEI`/`^BSESN`
  map to NSE/BSE so Indian indices report correct market hours.
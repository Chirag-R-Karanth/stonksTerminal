# Financial Terminal

A personal, Bloomberg-style desktop terminal for market data, screening,
fundamentals, portfolios, news, and macro economics — built with GTK 4
(PyGObject), SQLite, DuckDB, and an R analytics backend.

## Features

- **Command system** — a prompt-driven interface (`SCREEN PE<20`, `PORTFOLIO
  BUY AAPL 10 250`, `AAPL CHART`, `COMPARE AAPL MSFT`, `MACRO US_DGS10`, …).
  Type `HELP` for the full command reference.
- **Market data** — quotes, histories, and symbol search via pluggable
  providers (Yahoo Finance, Alpha Vantage) with local caching.
- **Screener** — filter symbols by fundamentals (PE, EV/EBITDA, margins, ROE,
  …) across a configurable universe plus your watchlist and portfolio.
- **Portfolio** — transactions, holdings, allocation, and performance/risk
  analytics (Sharpe, Sortino, VaR, drawdowns, beta/alpha vs a benchmark).
- **News & macro** — RSS headlines with ticker tagging and FRED economic
  series (Fed funds, CPI, yields, …).
- **Analytics in R** — performance, risk, valuation (DCF), multiples,
  correlations, and indicators (SMA, RSI, MACD, Bollinger, ATR, VWAP) are
  computed with R 4.x via a JSON bridge.
- **Demo mode** — `--demo` uses a local, deterministic synthetic provider so
  the full app can be exercised offline. Demo data is always labeled.
- **Evidence & provenance** — every data row records source, fetch time, and
  status (live / cached / stale / offline / demo / error).

## Requirements

- Python 3.11+ with PyGObject (GTK 4) working (system PyGObject is fine;
  create the venv with `--system-site-packages`).
- R 4.5.3+ with the `jsonlite`, `zoo`, and `xts` packages (`Rscript` on PATH).
  If any are missing the app still runs with graceful degradation.
- Optional: `ffmpeg` or another screen-grab tool if you use the screenshot
  helper `scripts/gtksmoke.py` (runs the app, issues ~20 commands, and saves
  screenshots to disk).

## Quick start

```bash
python3 -m venv --system-site-packages .venv
.venv/bin/pip install -e .
.venv/bin/terminal                 # live data (needs network)
.venv/bin/terminal --demo          # synthetic offline data
.venv/bin/terminal --check         # environment self-check
.venv/bin/terminal --offline       # start without network access
```

Keyboard: `F1` SYMBOL, `F2` SECURITY, `F3` WATCHLIST, `F4` PORTFOLIO,
`F5` SCREENER, `F6` NEWS, `F7` MACRO, `F8` MARKETS, `Ctrl+R` REFRESH,
`Ctrl+L` CLEAR.

## Configuration

`config/default.toml` is merged with your user config at
`$XDG_CONFIG_HOME/financial-terminal/config.toml`. Per-user overrides win.
Key sections:

- `[data.cache]` — TTLs for quotes, prices, fundamentals, news, macro.
- `[screener]` — universe size and max fetch budget.
- `[session.*]` — exchange trading sessions (NSE, BSE, NYSE, LSE) driving
  market-hours status.
- `[macro_series]` — FRED series visible in the macro board.
- `[peers]` — peer groups used by `SYMBOL PEERS`.

`SETTINGS GET/SET/RESET` edits settings at runtime.

## Command cheat sheet

```
HELP [TOPIC]                 HELP FILTERS / HELP SYMBOLS / HELP PORTFOLIO
STATUS                       environment + provider summary
SYMBOL [ACTION] [PERIOD]     AAPL / AAPL CHART / AAPL FIN / AAPL VAL /
                             AAPL NEWS / AAAPL RISK / ^GSPC
SCREEN PE<20 DEBT/EQUITY<0.5
SCREEN SAVE NAME PE<20       SCREEN LOAD NAME / SCREEN DELETE NAME
WATCHLIST [ADD|REMOVE|CREATE|DELETE|USE] ...        (alias WL)
PORTFOLIO BUY SYM QTY PRICE [DATE]                  (alias POS)
PORTFOLIO ADD / SELL / DIV / DEPOSIT / WITHDRAWAL
PORTFOLIO BENCHMARK SYM / PORTFOLIO RISK / PERFORMANCE / HISTORY
COMPARE AAPL MSFT [GOOG ...]
NEWS [QUERY] / MACRO SERIES / MACRO / MARKETS
HISTORY [N] / CLEAR / REFRESH / WORKSPACE NEW|USE|SAVE / PROVENANCE [SYMBOL]
```

Filters accept `>`, `<`, `>=`, `<=`, `==`, `!=`, percentages (`PE<20%`),
decimal/scientific values, and `[A-Za-z0-9_.-]` symbols.

## Architecture

```
app/            GTK UI, commands, services, state, main entry
data/           providers (market/fundamentals/news/macro), models, caching
database/       SQLite metadata + DuckDB/Parquet price & screening store
analytics/      R worker + JSON bridge + Python API (PerformanceStats, DCF…)
config/         default.toml
tests/          pytest suite (demo-mode end-to-end + unit tests)
docs/           additional documentation
```

Data is kept local: SQLite (`~/.local/share/financial-terminal/`) stores
settings, history, holdings, and caches; DuckDB + Parquet store price
history and the screener universe. Nothing leaves the machine beyond the
provider requests configured.

## Testing

```bash
.venv/bin/python -m pytest
```

The suite covers tokenizer/parser, command registry + engine handlers,
formatting, repositories, market-hours logic, demo provider, Yahoo/RSS
parsing fixtures, services end-to-end in demo mode, and the R analytics
bridge (skipped automatically if R/jsonlite/zoo/xts are missing).

## Labels & honesty

Demo and modeled outputs are always labeled (`DEMO DATA — not real market
data`, `MODEL: current holdings at constant weights`). Fundamentals and
prices are fetched from configured providers or served from cache; the app
never fabricates unpublished financial figures.
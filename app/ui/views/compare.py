from __future__ import annotations

from typing import Any, Callable

from app.ui import format, theme
from app.ui.charts import Chart, ChartData, Series
from app.ui.gtk import Gtk
from app.ui.table import Column, DataTable
from app.ui.views.base import View, grid_of

PALETTE = [theme.AMBER, theme.BLUE, theme.GREEN, theme.MAGENTA, theme.CYAN, theme.RED, theme.YELLOW]

METRIC_COLUMNS = [
    Column("symbol", "Symbol", align="l", width=110, fmt=lambda r: r["symbol"],
           css=lambda r: "ft-accent", sort_key=lambda r: r["symbol"]),
    Column("last", "Last", align="r", width=100, fmt=lambda r: format.num(r.get("last")),
           sort_key=lambda r: r.get("last") or 0),
    Column("change_pct", "Chg %", align="r", width=90, fmt=lambda r: format.pct(r.get("change_pct")),
           css=lambda r: format.sign_class(r.get("change_pct")),
           sort_key=lambda r: r.get("change_pct") if r.get("change_pct") is not None else -999),
    Column("cagr", "CAGR", align="r", width=90, fmt=lambda r: format.pct(r.get("cagr")),
           css=lambda r: format.sign_class(r.get("cagr")),
           sort_key=lambda r: r.get("cagr") if r.get("cagr") is not None else -999),
    Column("volatility", "Vol", align="r", width=90, fmt=lambda r: format.pct(r.get("volatility")),
           sort_key=lambda r: r.get("volatility") if r.get("volatility") is not None else -999),
    Column("sharpe", "Sharpe", align="r", width=90, fmt=lambda r: format.num(r.get("sharpe")),
           sort_key=lambda r: r.get("sharpe") if r.get("sharpe") is not None else -999),
    Column("max_drawdown", "MaxDD", align="r", width=90, fmt=lambda r: format.pct(r.get("max_drawdown")),
           css=lambda r: "ft-down" if r.get("max_drawdown") else "",
           sort_key=lambda r: r.get("max_drawdown") if r.get("max_drawdown") is not None else -999),
    Column("error", "Note", align="l", fmt=lambda r: r.get("error", ""), css=lambda r: "ft-err" if r.get("error") else ""),
]


class CompareView(View):
    view_name = "compare"

    def __init__(self, state: Any, runner: Any, open_panel: Callable[..., None] | None = None):
        super().__init__(state, runner, open_panel)
        self.symbols: list[str] = []
        self.period = "1Y"

    def mount(self, payload: dict[str, Any]) -> None:
        symbols = payload.get("symbols") or []
        self.symbols = [str(s).upper() for s in symbols]
        self.set_title("COMPARE  " + "  ·  ".join(self.symbols))
        super().mount(payload)

    def load(self, force: bool = False) -> None:
        symbols = list(self.symbols)
        period = self.period
        self.set_busy("loading comparison…")

        def work():
            import pandas as pd

            series: dict[str, Any] = {}
            errors: dict[str, str] = {}
            quotes: dict[str, Any] = {}
            stats_map: dict[str, Any] = {}
            analytics = self.state.analytics
            for symbol in symbols:
                quote = self.state.market.quote(symbol, force=force)
                quotes[symbol] = quote
                if quote.data is None:
                    errors[symbol] = quote.message or "no quote"
                history = self.state.market.history(symbol, period, force=force)
                if history.data is None or not history.data.candles:
                    errors[symbol] = errors.get(symbol) or history.message or "no history"
                    continue
                candles = history.data.candles
                series[symbol] = pd.Series(
                    {pd.Timestamp(c.ts): float(c.close) for c in candles}, name=symbol, dtype=float
                ).sort_index()
                if analytics.available:
                    try:
                        stats_map[symbol] = analytics.performance(
                            [float(c.close) for c in candles],
                            [format.iso_date(c.ts) for c in candles],
                        ).__dict__
                    except Exception as exc:
                        errors[symbol] = errors.get(symbol) or f"stats: {exc}"
            frame = pd.DataFrame(series).sort_index()
            norm = None
            corr = None
            if not frame.empty:
                norm = frame.apply(lambda col: col / col.dropna().iloc[0] * 100.0 if col.notna().any() else col)
                returns = frame.pct_change().dropna(how="all")
                if analytics.available and len(returns) > 10:
                    try:
                        corr = analytics.correlation(
                            list(returns.columns),
                            {col: returns[col].fillna(0.0).tolist() for col in returns.columns},
                        )
                    except Exception as exc:
                        errors["correlation"] = str(exc)
            return {
                "frame_dates": [d.strftime("%Y-%m-%d") for d in norm.index] if norm is not None else [],
                "norm": {col: [round(float(v), 4) for v in norm[col].tolist()] for col in norm.columns}
                if norm is not None
                else {},
                "quotes": quotes,
                "stats": stats_map,
                "corr": corr,
                "errors": errors,
                "columns": [str(c) for c in (norm.columns if norm is not None else [])],
            }

        self.runner.submit(work, self._on_data)

    def _on_data(self, payload: Any) -> None:
        if isinstance(payload, Exception):
            self.set_error(str(payload))
            return
        self.clear_content()
        dates = payload.get("frame_dates") or []
        norm = payload.get("norm") or {}
        if dates and norm:
            chart = Chart(height=280)
            chart_data = ChartData(dates=dates, y_fmt=lambda v: f"{v:.0f}")
            for index, symbol in enumerate(payload.get("columns", [])):
                chart_data.series.append(
                    Series(symbol, norm.get(symbol, []), PALETTE[index % len(PALETTE)], width=1.6)
                )
            chart.set_data(chart_data)
            self.content.append(chart)
        else:
            note = Gtk.Label(label="no overlapping history for chart", xalign=0)
            note.add_css_class("ft-warn")
            self.content.append(note)

        quotes = payload.get("quotes") or {}
        stats = payload.get("stats") or {}
        errors = payload.get("errors") or {}
        rows = []
        for symbol in self.symbols:
            quote = quotes.get(symbol)
            result = quote if quote is not None else None
            row = {
                "symbol": symbol,
                "last": result.data.price if result and result.data else None,
                "change_pct": result.data.change_pct if result and result.data else None,
                "error": errors.get(symbol, ""),
            }
            row.update(stats.get(symbol) or {})
            rows.append(row)
        table = DataTable(
            METRIC_COLUMNS,
            on_activate=lambda row: self.open_panel({"view": "security", "symbol": row["symbol"], "action": "chart"})
            if self.open_panel
            else None,
        )
        table.set_rows(rows)
        self.content.append(table)

        corr = payload.get("corr")
        if corr and corr.get("symbols") and corr.get("matrix"):
            head = Gtk.Label(label=f"CORRELATION of daily returns ({self.period})", xalign=0)
            head.add_css_class("ft-section")
            self.content.append(head)
            self.content.append(_corr_grid(corr["symbols"], corr["matrix"]))
        elif errors.get("correlation"):
            note = Gtk.Label(label=f"correlation unavailable: {errors['correlation']}", xalign=0)
            note.add_css_class("ft-warn")
            self.content.append(note)
        from data.models import DataResult

        worst = "live"
        if errors:
            worst = "stale"
        self.show_result(
            DataResult(data=rows, status=worst, provider=self.state.market.name),
            extra=f"{len(self.symbols)} symbols · {len(dates)} points",
        )


def _corr_grid(symbols: list[str], matrix: list[list[float]]) -> Gtk.Grid:
    grid = Gtk.Grid()
    grid.set_column_spacing(8)
    grid.set_row_spacing(2)
    for col, symbol in enumerate(symbols):
        label = Gtk.Label(label=symbol, xalign=1)
        label.add_css_class("ft-dim")
        grid.attach(label, col + 1, 0, 1, 1)
    for row_index, row_values in enumerate(matrix):
        name = Gtk.Label(label=symbols[row_index] if row_index < len(symbols) else "?", xalign=0)
        name.add_css_class("ft-accent")
        grid.attach(name, 0, row_index + 1, 1, 1)
        for col_index, value in enumerate(row_values):
            cell = Gtk.Label(label=format.num(value, 2), xalign=1)
            if value is not None and abs(float(value)) > 0.6:
                cell.add_css_class("ft-up" if float(value) > 0 else "ft-down")
            grid.attach(cell, col_index + 1, row_index + 1, 1, 1)
    return grid

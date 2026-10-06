from __future__ import annotations

from typing import Any, Callable

from app.ui import format, theme
from app.ui.charts import Chart, ChartData, Series
from app.ui.gtk import Gtk
from app.ui.table import Column, DataTable
from app.ui.views.base import View, grid_of

HOLDING_COLUMNS = [
    Column("symbol", "Symbol", align="l", width=110, fmt=lambda r: r["symbol"],
           sort_key=lambda r: r["symbol"]),
    Column("name", "Name", align="l", fmt=lambda r: r.get("name") or format.NA,
           sort_key=lambda r: r.get("name") or ""),
    Column("quantity", "Qty", align="r", width=80, fmt=lambda r: format.num(r.get("quantity"), 2),
           sort_key=lambda r: r.get("quantity") or 0),
    Column("avg_cost", "Avg Cost", align="r", width=95, fmt=lambda r: format.num(r.get("avg_cost")),
           sort_key=lambda r: r.get("avg_cost") or 0),
    Column("price", "Price", align="r", width=95, fmt=lambda r: format.num(r.get("price")),
           sort_key=lambda r: r.get("price") or 0),
    Column("change_pct", "Chg %", align="r", width=85, fmt=lambda r: format.pct(r.get("change_pct")),
           css=lambda r: format.sign_class(r.get("change_pct")),
           sort_key=lambda r: r.get("change_pct") if r.get("change_pct") is not None else -999),
    Column("value", "Value", align="r", width=110, fmt=lambda r: format.compact(r.get("value")),
           sort_key=lambda r: r.get("value") or 0),
    Column("weight", "Weight", align="r", width=85, fmt=lambda r: format.pct(r.get("weight")),
           sort_key=lambda r: r.get("weight") or 0),
    Column("unrealized", "Unrealized", align="r", width=110, fmt=lambda r: format.compact(r.get("unrealized")),
           css=lambda r: format.sign_class(r.get("unrealized")),
           sort_key=lambda r: r.get("unrealized") or 0),
    Column("realized", "Realized", align="r", width=95, fmt=lambda r: format.compact(r.get("realized")),
           css=lambda r: format.sign_class(r.get("realized")),
           sort_key=lambda r: r.get("realized") or 0),
    Column("status", "Status", align="l", width=80, fmt=lambda r: r.get("status", "")),
]

TX_COLUMNS = [
    Column("id", "#", align="r", width=50, fmt=lambda r: str(r.get("id", "")),
           sort_key=lambda r: r.get("id") or 0),
    Column("trade_date", "Date", align="l", width=100, fmt=lambda r: r.get("trade_date", ""),
           sort_key=lambda r: r.get("trade_date", "")),
    Column("symbol", "Symbol", align="l", width=110, fmt=lambda r: r.get("symbol", ""),
           sort_key=lambda r: r.get("symbol", "")),
    Column("side", "Side", align="l", width=100, fmt=lambda r: r.get("side", ""),
           css=lambda r: "ft-up" if r.get("side") == "BUY" else ("ft-down" if r.get("side") == "SELL" else "ft-dim")),
    Column("quantity", "Qty", align="r", width=90, fmt=lambda r: format.num(r.get("quantity"), 2)),
    Column("price", "Price", align="r", width=100, fmt=lambda r: format.num(r.get("price"))),
    Column("fees", "Fees", align="r", width=70, fmt=lambda r: format.num(r.get("fees"))),
]

TAB_LABELS = (
    ("holdings", "HOLDINGS"),
    ("risk", "RISK"),
    ("performance", "PERFORMANCE"),
    ("history", "HISTORY"),
)

PERIODS = ("1M", "3M", "6M", "1Y", "2Y", "5Y")


class PortfolioView(View):
    view_name = "portfolio"

    def __init__(self, state: Any, runner: Any, open_panel: Callable[..., None] | None = None):
        super().__init__(state, runner, open_panel)
        self.tab = "holdings"
        self.period = "1Y"

        self.summary_label = Gtk.Label(label="", xalign=0)
        self.summary_label.add_css_class("ft-accent")
        self.content.append(self.summary_label)

        self.tab_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        group = None
        self.tab_buttons: dict[str, Gtk.ToggleButton] = {}
        for name, label in TAB_LABELS:
            btn = Gtk.ToggleButton(label=label)
            btn.add_css_class("ft-button")
            if group is None:
                group = btn
                btn.set_active(True)
            else:
                btn.set_group(group)
            btn.connect("toggled", self._on_tab, name)
            self.tab_bar.append(btn)
            self.tab_buttons[name] = btn
        self.content.append(self.tab_bar)

        self.stack = Gtk.Stack()
        self.stack.set_vexpand(True)
        self.pages: dict[str, Gtk.Box] = {}
        for name, _ in TAB_LABELS:
            page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            self.stack.add_named(page, name)
            self.pages[name] = page
        self.content.append(self.stack)

    def mount(self, payload: dict[str, Any]) -> None:
        self.set_title("PORTFOLIO  " + str(self.state.portfolio.meta().get("benchmark") or ""))
        tab = str(payload.get("tab", "") or self.tab)
        period = str(payload.get("period", "") or "")
        if period:
            self.period = period
        if tab in self.pages:
            self.tab = tab
            for name, button in self.tab_buttons.items():
                if button.get_active() != (name == self.tab):
                    button.set_active(name == self.tab)
            self.stack.set_visible_child(self.pages[self.tab])
        super().mount(payload)

    def _on_tab(self, button: Gtk.ToggleButton, name: str) -> None:
        if not button.get_active():
            return
        self.tab = name
        self.stack.set_visible_child(self.pages[name])
        self.load(force=False)

    def load(self, force: bool = False) -> None:
        tab = self.tab
        page = self.pages[tab]
        while (child := page.get_first_child()) is not None:
            page.remove(child)
        if tab == "holdings":
            self._load_holdings(force)
        elif tab == "risk":
            self._load_risk(force)
        elif tab == "performance":
            self._load_performance(force)
        else:
            self._load_history()

    def _load_holdings(self, force: bool) -> None:
        self.set_busy("loading holdings…")

        def work():
            summary = self.state.portfolio.summary(force=force)
            xirr = self.state.portfolio.xirr()
            if xirr is not None:
                summary["xirr"] = xirr
            return summary

        self.runner.submit(work, self._on_holdings)

    def _on_holdings(self, result: Any) -> None:
        page = self.pages["holdings"]
        while (child := page.get_first_child()) is not None:
            page.remove(child)
        if isinstance(result, Exception):
            self.set_error(str(result))
            return
        rows = result.get("rows", [])
        bits = [
            f"value {format.compact(result.get('market_value'))}",
            f"unrealized {format.compact(result.get('unrealized'))}",
            f"realized {format.compact(result.get('realized'))}",
            f"dividends {format.compact(result.get('dividends'))}",
            f"day {format.compact(result.get('day_change'))}",
        ]
        if result.get("xirr") is not None:
            bits.append(f"XIRR {format.pct(result.get('xirr'))}")
        if result.get("total_return") is not None:
            bits.append(f"return {format.pct(result.get('total_return'))}")
        self.summary_label.set_text("   ·   ".join(bits))
        table = DataTable(
            HOLDING_COLUMNS,
            on_activate=lambda row: self.open_panel(
                {"view": "security", "symbol": row.get("symbol", ""), "action": "overview"}
            )
            if self.open_panel
            else None,
        )
        table.set_rows(rows)
        table.set_vexpand(True)
        page.append(table)
        from data.models import DataResult

        self.show_result(
            DataResult(data=rows, status=result.get("status", "live"), provider=self.state.market.name),
            extra=f"{result.get('holdings', 0)} holdings",
        )

    def _load_risk(self, force: bool) -> None:
        page = self.pages["risk"]
        self._spinner(page, "computing portfolio risk (R)…")
        period = self.period

        def work():
            return self.state.portfolio.risk(period=period, force=force)

        self.runner.submit(work, self._on_risk)

    def _spinner(self, page: Gtk.Box, text: str) -> None:
        label = Gtk.Label(label=text)
        label.add_css_class("ft-dim")
        page.append(label)

    def _on_risk(self, result: Any) -> None:
        page = self.pages["risk"]
        while (child := page.get_first_child()) is not None:
            page.remove(child)
        if isinstance(result, Exception):
            self.set_error(str(result))
            return
        data = result.data
        if data is None:
            self.set_error(result.message or "risk unavailable")
            return
        period_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        group = None
        for name in PERIODS:
            btn = Gtk.ToggleButton(label=name)
            btn.add_css_class("ft-button")
            if group is None:
                group = btn
            else:
                btn.set_group(group)
            btn.set_active(name == self.period)
            btn.connect("toggled", self._on_period, name)
            period_row.append(btn)
        page.append(period_row)
        label = Gtk.Label(label=data.get("model", ""), xalign=0)
        label.add_css_class("ft-warn")
        page.append(label)
        conc = data.get("concentration") or {}
        pairs = [
            ("Positions", format.int_num(conc.get("count")), ""),
            ("Max weight", format.pct(conc.get("max_weight")), ""),
            ("HHI", format.num(conc.get("hhi"), 3), ""),
        ]
        stats = data.get("stats") or {}
        for key, label_text, kind in (
            ("mean_return_annualized", "Return (ann.)", "pct"),
            ("volatility", "Volatility", "pct"),
            ("sharpe", "Sharpe", "num"),
            ("sortino", "Sortino", "num"),
            ("max_drawdown", "Max drawdown", "pct"),
            ("var", "VaR 95", "pct"),
            ("cvar", "CVaR 95", "pct"),
            ("win_rate", "Win rate", "pct"),
        ):
            value = stats.get(key)
            text = format.NA if value is None else (format.pct(value) if kind == "pct" else format.num(value))
            pairs.append((label_text, text, ""))
        bench_stats = stats.get("benchmark") or {}
        if bench_stats:
            for key, label_text, kind in (
                ("beta", "Beta", "num"),
                ("alpha_annualized", "Alpha (ann.)", "pct"),
                ("tracking_error", "Tracking error", "pct"),
                ("information_ratio", "Info ratio", "num"),
                ("correlation", "Correlation", "num"),
            ):
                value = bench_stats.get(key)
                text = format.NA if value is None else (format.pct(value) if kind == "pct" else format.num(value))
                pairs.append((label_text, text, ""))
        page.append(grid_of(pairs, columns=3))
        sector = data.get("sector_weights") or {}
        if sector:
            columns = [
                Column("sector", "Sector", align="l", fmt=lambda r: r["sector"],
                       sort_key=lambda r: r["sector"]),
                Column("weight", "Weight", align="r", width=110,
                       fmt=lambda r: format.pct(r.get("weight")),
                       sort_key=lambda r: r.get("weight") or 0),
            ]
            table = DataTable(columns)
            table.set_rows([{"sector": k, "weight": v} for k, v in sorted(sector.items(), key=lambda kv: -kv[1])])
            page.append(table)
        self.show_result(result, extra=f"period {data.get('period')}")

    def _on_period(self, button: Gtk.ToggleButton, name: str) -> None:
        if not button.get_active() or name == self.period:
            return
        self.period = name
        if self.tab in ("risk", "performance"):
            self.load(force=True)

    def _load_performance(self, force: bool) -> None:
        page = self.pages["performance"]
        self._spinner(page, "computing performance (R)…")
        period = self.period

        def work():
            return self.state.portfolio.performance(period=period, force=force)

        self.runner.submit(work, self._on_performance)

    def _on_performance(self, result: Any) -> None:
        page = self.pages["performance"]
        while (child := page.get_first_child()) is not None:
            page.remove(child)
        if isinstance(result, Exception):
            self.set_error(str(result))
            return
        data = result.data
        if data is None:
            self.set_error(result.message or "performance unavailable")
            return
        period_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        group = None
        for name in PERIODS:
            btn = Gtk.ToggleButton(label=name)
            btn.add_css_class("ft-button")
            if group is None:
                group = btn
            else:
                btn.set_group(group)
            btn.set_active(name == self.period)
            btn.connect("toggled", self._on_period, name)
            period_row.append(btn)
        page.append(period_row)
        label = Gtk.Label(label=data.get("model", ""), xalign=0)
        label.add_css_class("ft-warn")
        page.append(label)
        chart = Chart(height=280)
        chart_data = ChartData(
            dates=data.get("dates", []),
            series=[Series("portfolio", data.get("equity", []), theme.AMBER)],
            y_fmt=lambda v: f"{v:.3f}",
        )
        benchmark = data.get("benchmark")
        if benchmark and benchmark.get("equity"):
            b_dates = benchmark.get("dates", [])
            b_vals = benchmark.get("equity", [])
            if b_dates and b_dates != data.get("dates"):
                lookup = dict(zip(data.get("dates", []), data.get("equity", [])))
                aligned_dates = [d for d in b_dates if d in lookup]
                aligned_vals = [lookup[d] for d in aligned_dates]
                chart_data.dates = aligned_dates
                chart_data.series = [Series("portfolio", aligned_vals, theme.AMBER)]
            chart_data.series.append(Series(str(benchmark.get("symbol", "bench")), b_vals, theme.BLUE))
        chart.set_data(chart_data)
        page.append(chart)
        stats = data.get("stats") or {}
        pairs = []
        for key, label_text, kind in (
            ("total_return", "Total return", "pct"),
            ("cagr", "CAGR", "pct"),
            ("volatility", "Volatility", "pct"),
            ("sharpe", "Sharpe", "num"),
            ("sortino", "Sortino", "num"),
            ("max_drawdown", "Max drawdown", "pct"),
            ("win_rate", "Win rate", "pct"),
        ):
            value = stats.get(key)
            text = format.NA if value is None else (format.pct(value) if kind == "pct" else format.num(value))
            pairs.append((label_text, text, ""))
        page.append(grid_of(pairs, columns=4))
        beta_alpha = data.get("beta_alpha")
        if beta_alpha:
            bench = (benchmark or {}).get("symbol", "benchmark")
            pairs = [
                (f"Beta vs {bench}", format.num(beta_alpha.get("beta")), ""),
                (f"Alpha vs {bench}", format.pct(beta_alpha.get("alpha_annualized")), format.sign_class(beta_alpha.get("alpha_annualized"))),
                ("R²", format.num(beta_alpha.get("r_squared")), ""),
            ]
            page.append(grid_of(pairs, columns=3))
        if data.get("errors"):
            note = Gtk.Label(label=f"partial data: {data['errors']}", xalign=0)
            note.add_css_class("ft-warn")
            page.append(note)
        self.show_result(result, extra=f"period {data.get('period')}")

    def _load_history(self) -> None:
        page = self.pages["history"]
        rows = self.state.portfolio.transactions()
        table = DataTable(TX_COLUMNS)
        table.set_rows(rows)
        table.set_vexpand(True)
        page.append(table)
        hint = Gtk.Label(label="modify: PORTFOLIO ADD/SELL/DIV ... · delete: PORTFOLIO DELETE <id>", xalign=0)
        hint.add_css_class("ft-dim")
        page.append(hint)
        from data.models import DataResult

        self.show_result(DataResult(data=rows, status="cached"), extra=f"{len(rows)} transactions")

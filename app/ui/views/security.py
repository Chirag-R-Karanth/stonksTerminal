from __future__ import annotations

import logging
from typing import Any, Callable

from analytics.api import DcfResult, PerformanceStats
from app.ui import format, theme
from app.ui.charts import Chart, ChartData, Series
from app.ui.gtk import Gtk
from app.ui.table import Column, DataTable
from app.ui.views.base import View, grid_of

log = logging.getLogger(__name__)

PERIODS = ("INTRA", "1D", "5D", "1M", "3M", "6M", "1Y", "2Y", "5Y", "MAX")
TAB_LABELS = (
    ("overview", "OVERVIEW"),
    ("chart", "CHART"),
    ("fin", "FIN"),
    ("val", "VAL"),
    ("earnings", "EARNINGS"),
    ("risk", "RISK"),
)

FIN_ROWS = [
    ("revenue", "Revenue", 0),
    ("gross_profit", "Gross Profit", 0),
    ("operating_income", "Operating Income", 0),
    ("ebitda", "EBITDA", 0),
    ("net_income", "Net Income", 0),
    ("diluted_eps", "Diluted EPS", 2),
    ("total_assets", "Total Assets", 0),
    ("total_liabilities", "Total Liabilities", 0),
    ("shareholders_equity", "Shareholders' Equity", 0),
    ("cash", "Cash & Equivalents", 0),
    ("total_debt", "Total Debt", 0),
    ("operating_cash_flow", "Operating Cash Flow", 0),
    ("capital_expenditure", "Capital Expenditure", 0),
    ("free_cash_flow", "Free Cash Flow", 0),
    ("research_and_development", "R&D", 0),
]

OVERVIEW_FIELDS = [
    ("price", "Price", "price"),
    ("market_cap", "Market Cap", "compact"),
    ("trailing_pe", "P/E (trailing)", "num"),
    ("forward_pe", "P/E (forward)", "num"),
    ("peg_ratio", "PEG", "num"),
    ("price_to_book", "P/B", "num"),
    ("price_to_sales", "P/S", "num"),
    ("ev_to_ebitda", "EV/EBITDA", "num"),
    ("beta", "Beta", "num"),
    ("fifty_two_week_high", "52w High", "price"),
    ("fifty_two_week_low", "52w Low", "price"),
    ("dividend_yield", "Div Yield", "pct%"),
    ("payout_ratio", "Payout", "pct"),
    ("roe", "ROE", "pct"),
    ("roa", "ROA", "pct"),
    ("profit_margin", "Net Margin", "pct"),
    ("gross_margin", "Gross Margin", "pct"),
    ("operating_margin", "Op Margin", "pct"),
    ("revenue_growth", "Rev Growth", "pct"),
    ("free_cash_flow", "Free Cash Flow", "compact"),
    ("target_mean_price", "Target Mean", "price"),
    ("analyst_count", "Analysts", "int"),
]


class SecurityView(View):
    view_name = "security"

    def __init__(
        self,
        state: Any,
        runner: Any,
        open_panel: Callable[[dict[str, Any]], None] | None = None,
    ):
        super().__init__(state, runner, open_panel)
        self.symbol = ""
        self.action = "overview"
        self.period = "1Y"
        self.statement_period = "annual"
        self.quote_result = None
        self.fund_result = None
        self.profile = None
        self.history_cache: dict[tuple[str, str], Any] = {}
        self.tab_cache: dict[str, Callable[[], None]] = {}
        self.overlay = {"sma20": False, "sma50": False, "ema20": False, "boll": False, "rsi": False}

        self.quote_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        self.quote_box.set_margin_top(2)
        self.price_label = Gtk.Label(label="", xalign=0)
        self.price_label.add_css_class("ft-title")
        self.change_label = Gtk.Label(label="", xalign=0)
        self.detail_label = Gtk.Label(label="", xalign=0)
        self.detail_label.add_css_class("ft-dim")
        self.quote_box.append(self.price_label)
        self.quote_box.append(self.change_label)
        self.quote_box.append(self.detail_label)
        self.content.append(self.quote_box)

        self.tab_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self.tab_buttons: dict[str, Gtk.ToggleButton] = {}
        group = None
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
        self.stack.set_visible_child(self.pages["overview"])

    def mount(self, payload: dict[str, Any]) -> None:
        symbol = str(payload.get("symbol", "")).upper()
        action = str(payload.get("action", "") or self.action)
        period = str(payload.get("period", "") or "")
        if symbol and symbol != self.symbol:
            self.symbol = symbol
            self.quote_result = None
            self.fund_result = None
            self.profile = None
            self.history_cache.clear()
            self.tab_cache.clear()
        if action in self.pages:
            self.action = action
        if period:
            self.period = period
        for name, button in self.tab_buttons.items():
            if button.get_active() != (name == self.action):
                button.set_active(name == self.action)
        self.stack.set_visible_child(self.pages[self.action])
        super().mount(payload)

    def _on_tab(self, button: Gtk.ToggleButton, name: str) -> None:
        if not button.get_active():
            return
        self.action = name
        self.stack.set_visible_child(self.pages[name])
        if name in self.tab_cache:
            self.tab_cache[name]()
        else:
            self._load_tab(force=False)

    def load(self, force: bool = False) -> None:
        if not self.symbol:
            return
        if force:
            self.history_cache.clear()
            self.tab_cache.clear()
        self.set_busy(f"loading {self.symbol}…")
        symbol = self.symbol

        def work() -> dict[str, Any]:
            profile = None
            try:
                profile = self.state.market.resolve(symbol)
            except Exception as exc:
                log.warning("resolve %s failed: %s", symbol, exc)
            quote = self.state.market.quote(symbol, force=force)
            fund = self.state.security.fundamentals(symbol, force=force)
            return {"profile": profile, "quote": quote, "fund": fund}

        self.runner.submit(work, self._on_base_data)

    def _on_base_data(self, result: Any) -> None:
        if isinstance(result, Exception):
            self.set_error(str(result))
            return
        self.profile = result["profile"]
        self.quote_result = result["quote"]
        self.fund_result = result["fund"]
        self._render_header()
        primary = (
            self.quote_result
            if self.quote_result and (self.quote_result.ok or self.quote_result.message)
            else self.fund_result
        )
        self.show_result(primary)
        self._load_tab(force=False)

    def _render_header(self) -> None:
        profile = self.profile
        name = ""
        exchange = ""
        if profile:
            name = profile.name
            exchange = profile.exchange
        if self.fund_result and self.fund_result.data:
            name = name or self.fund_result.data.text_fields.get("name", "")
            exchange = exchange or self.fund_result.data.text_fields.get("exchange", "")
        suffix = f" — {name}" if name else ""
        self.set_title(f"{self.symbol}{suffix}" + (f"  ·  {exchange}" if exchange else ""))
        quote = self.quote_result.data if self.quote_result else None
        if quote is None:
            self.price_label.set_text(format.NA)
            self.change_label.set_text("")
            self.detail_label.set_text("no quote")
            return
        self.price_label.set_text(format.num(quote.price, 2))
        change = quote.change
        change_pct = quote.change_pct
        change_text = ""
        if change is not None and change_pct is not None:
            change_text = f"{change:+,.2f}  ({change_pct:+.2f}%)"
        self.change_label.set_text(change_text)
        css = format.sign_class(change_pct)
        self.change_label.set_css_classes([css] if css else [])
        details = []
        if quote.market_cap:
            details.append(f"mcap {format.compact(quote.market_cap)}")
        if quote.fifty_two_high and quote.fifty_two_low:
            details.append(f"52w {format.num(quote.fifty_two_low)}–{format.num(quote.fifty_two_high)}")
        if quote.volume:
            details.append(f"vol {format.compact(quote.volume, 1)}")
        if quote.currency:
            details.append(quote.currency)
        if quote.market_time:
            details.append(str(quote.market_time))
        self.detail_label.set_text("  ·  ".join(details))

    def _load_tab(self, force: bool = False) -> None:
        tab = self.action
        page = self.pages[tab]
        while (child := page.get_first_child()) is not None:
            page.remove(child)
        loader = getattr(self, f"_load_{tab}", None)
        if loader:
            loader(force)

    def _spinner(self, page: Gtk.Box, text: str) -> None:
        label = Gtk.Label(label=text)
        label.add_css_class("ft-dim")
        page.append(label)

    def _load_overview(self, force: bool) -> None:
        page = self.pages["overview"]
        fund = self.fund_result.data if self.fund_result else None
        if fund is None:
            self._spinner(page, "fundamentals unavailable" + (f": {self.fund_result.message}" if self.fund_result else ""))
            return
        pairs: list[tuple[str, str, str]] = []
        for key, label, kind in OVERVIEW_FIELDS:
            value = fund.fields.get(key)
            if value is None:
                text = format.NA
            elif kind == "compact":
                text = format.compact(value)
            elif kind == "pct":
                text = format.pct_abs(value) if key == "dividend_yield" else format.pct_abs(value)
            elif kind == "price":
                text = format.num(value)
            elif kind == "int":
                text = format.int_num(value)
            else:
                text = format.num(value)
            css = ""
            if key in ("roe", "profit_margin", "revenue_growth", "gross_margin", "operating_margin"):
                css = format.sign_class(value)
            pairs.append((label, text, css))
        grid = grid_of(pairs, columns=3)
        page.append(grid)

        text = fund.text_fields
        meta_bits = []
        if text.get("sector"):
            meta_bits.append(text["sector"])
        if text.get("industry"):
            meta_bits.append(text["industry"])
        if text.get("employees"):
            meta_bits.append(f"{text['employees']} employees")
        if meta_bits:
            label = Gtk.Label(label="  ·  ".join(meta_bits), xalign=0)
            label.add_css_class("ft-dim")
            page.append(label)
        summary = text.get("summary", "")
        if summary:
            expander = Gtk.Expander(label="business summary")
            expander.set_expanded(False)
            label = Gtk.Label(label=summary, xalign=0, wrap=True)
            label.add_css_class("ft-dim")
            expander.set_child(label)
            page.append(expander)
        peers = self.state.security.peers(self.symbol)
        if peers and self.open_panel:
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            head = Gtk.Label(label="peers:", xalign=0)
            head.add_css_class("ft-dim")
            box.append(head)
            for peer in peers:
                btn = Gtk.Button(label=peer)
                btn.add_css_class("ft-button")
                btn.connect("clicked", lambda *_p, p=peer: self.open_panel({"view": "security", "symbol": p, "action": "overview"}))
                box.append(btn)
            page.append(box)
        self.tab_cache["overview"] = lambda: self._load_overview(False)

    def _load_earnings(self, force: bool) -> None:
        page = self.pages["earnings"]
        fund = self.fund_result.data if self.fund_result else None
        if fund is None:
            self._spinner(page, "fundamentals unavailable")
            return
        fields = fund.fields
        text = fund.text_fields
        pairs = [
            ("Next earnings", text.get("next_earnings") or format.NA, "ft-accent"),
            ("EPS trailing", format.num(fields.get("eps_trailing")), ""),
            ("EPS forward", format.num(fields.get("eps_forward")), ""),
            ("Earnings growth", format.pct(fields.get("revenue_growth")) if fields.get("revenue_growth") is None else format.pct(fields.get("earnings_growth")), ""),
            ("Analyst target (mean)", format.num(fields.get("target_mean_price")), ""),
            ("Analysts", format.int_num(fields.get("analyst_count")), ""),
            ("Recommendation (1=strong buy)", format.num(fields.get("recommendation")), ""),
            ("Payout ratio", format.pct(fields.get("payout_ratio")), ""),
            ("Dividend rate", format.num(fields.get("dividend_rate")), ""),
        ]
        page.append(grid_of(pairs, columns=2))
        note = Gtk.Label(
            label="earnings history requires a calendar provider; only the next date is shown.",
            xalign=0,
        )
        note.add_css_class("ft-dim")
        page.append(note)
        self.tab_cache["earnings"] = lambda: self._load_earnings(False)

    def _load_chart(self, force: bool) -> None:
        page = self.pages["chart"]
        period_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        group = None
        for name in PERIODS:
            btn = Gtk.ToggleButton(label=name)
            btn.add_css_class("ft-button")
            if group is None:
                group = btn
                btn.set_active(name == self.period)
            else:
                btn.set_group(group)
                btn.set_active(name == self.period)
            btn.connect("toggled", self._on_period, name)
            period_row.append(btn)
        page.append(period_row)

        overlay_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        head = Gtk.Label(label="overlays:")
        head.add_css_class("ft-dim")
        overlay_row.append(head)
        for key, label in (("sma20", "SMA20"), ("sma50", "SMA50"), ("ema20", "EMA20"), ("boll", "BOLL"), ("rsi", "RSI")):
            btn = Gtk.ToggleButton(label=label)
            btn.add_css_class("ft-button")
            btn.set_active(self.overlay[key])
            btn.connect("toggled", self._on_overlay, key)
            overlay_row.append(btn)
        page.append(overlay_row)

        self._spinner(page, f"loading {self.symbol} {self.period}…")
        self._fetch_chart(force)

    def _on_period(self, button: Gtk.ToggleButton, name: str) -> None:
        if not button.get_active() or name == self.period:
            return
        self.period = name
        self._load_tab(force=True)

    def _on_overlay(self, button: Gtk.ToggleButton, key: str) -> None:
        self.overlay[key] = button.get_active()
        self._fetch_chart(force=False, recompute_only=True)

    def _fetch_chart(self, force: bool, recompute_only: bool = False) -> None:
        symbol = self.symbol
        period = self.period
        overlay = dict(self.overlay)
        cached = self.history_cache.get((symbol, period))
        if recompute_only and cached is None:
            return

        def work() -> dict[str, Any]:
            if cached is None:
                result = self.state.market.history(symbol, period, force=force)
                if result.data is not None:
                    self.history_cache[(symbol, period)] = result.data
                history = result.data
                status = result
            else:
                history = cached
                status = None
            payload: dict[str, Any] = {"history": history, "status": status, "overlay": overlay}
            if history is None or not history.candles:
                return payload
            closes = history.closes
            analytics = self.state.analytics
            if analytics.available and len(closes) >= 30:
                try:
                    if overlay.get("sma20"):
                        payload["sma20"] = analytics.indicator("sma", closes, window=20)
                    if overlay.get("sma50"):
                        payload["sma50"] = analytics.indicator("sma", closes, window=50)
                    if overlay.get("ema20"):
                        payload["ema20"] = analytics.indicator("ema", closes, window=20)
                    if overlay.get("boll"):
                        payload["boll"] = analytics.bollinger(closes, window=20, deviations=2.0)
                    if overlay.get("rsi"):
                        payload["rsi"] = analytics.indicator("rsi", closes, window=14)
                    payload["stats"] = analytics.performance(closes, [format.iso_date(c.ts) for c in history.candles]).__dict__
                except Exception as exc:
                    payload["r_error"] = str(exc)
                    log.warning("chart analytics failed: %s", exc)
            return payload

        self.runner.submit(work, self._on_chart_data)

    def _on_chart_data(self, payload: Any) -> None:
        if isinstance(payload, Exception):
            self.set_error(str(payload))
            return
        page = self.pages["chart"]
        while (child := page.get_first_child()) is not None:
            page.remove(child)
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
        overlay_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        head = Gtk.Label(label="overlays:")
        head.add_css_class("ft-dim")
        overlay_row.append(head)
        for key, label in (("sma20", "SMA20"), ("sma50", "SMA50"), ("ema20", "EMA20"), ("boll", "BOLL"), ("rsi", "RSI")):
            btn = Gtk.ToggleButton(label=label)
            btn.add_css_class("ft-button")
            btn.set_active(self.overlay.get(key, False))
            btn.connect("toggled", self._on_overlay, key)
            overlay_row.append(btn)
        page.append(overlay_row)

        history = payload.get("history")
        if history is None or not history.candles:
            status = payload.get("status")
            label = Gtk.Label(label=f"no price history{': ' + status.message if status and status.message else ''}", xalign=0)
            label.add_css_class("ft-err")
            page.append(label)
            return

        chart = Chart(height=300)
        data = ChartData(
            dates=[format.iso_date(c.ts) for c in history.candles],
            candles=[
                {"open": c.open, "high": c.high, "low": c.low, "close": c.close}
                for c in history.candles
            ],
            volumes=[float(c.volume or 0) for c in history.candles],
        )
        closes = [float(c.close) for c in history.candles]
        data.series = [Series(f"{self.symbol} close", closes, theme.AMBER)]
        colors = {"sma20": theme.BLUE, "sma50": theme.CYAN, "ema20": theme.MAGENTA}
        for key in ("sma20", "sma50", "ema20"):
            values = payload.get(key)
            if values:
                data.series.append(Series(key.upper(), list(values), colors[key], dashed=True))
        boll = payload.get("boll")
        if boll:
            upper = boll.get("upper") or []
            lower = boll.get("lower") or []
            if upper:
                data.series.append(Series("BOLL+", list(upper), theme.BLUE, dashed=True, width=1.0))
            if lower:
                data.series.append(Series("BOLL-", list(lower), theme.BLUE, dashed=True, width=1.0))
        rsi = payload.get("rsi")
        if rsi:
            data.sub = [Series("RSI14", list(rsi), theme.MAGENTA)]
            data.sub_guides = [30.0, 70.0]
            data.sub_min = 0.0
            data.sub_max = 100.0
        if not history.candles[0].open:
            data.candles = None
            data.series = [Series(f"{self.symbol} close", closes, theme.AMBER)]
        chart.set_data(data)
        page.append(chart)

        stats = payload.get("stats")
        stats_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=18)
        if stats:
            for label, key, kind in STAT_KEYS:
                item = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
                key_label = Gtk.Label(label=label)
                key_label.add_css_class("ft-dim")
                val_text = _fmt_stat(stats.get(key), kind)
                val = Gtk.Label(label=val_text)
                if key == "max_drawdown" and stats.get(key) is not None:
                    val.add_css_class("ft-down")
                if key == "cagr" and stats.get(key) is not None:
                    val.add_css_class(format.sign_class(stats.get(key)))
                item.append(key_label)
                item.append(val)
                stats_box.append(item)
        elif payload.get("r_error"):
            note = Gtk.Label(label=f"R analytics: {payload['r_error']}")
            note.add_css_class("ft-warn")
            stats_box.append(note)
        else:
            note = Gtk.Label(label="R analytics unavailable — stats skipped")
            note.add_css_class("ft-warn")
            stats_box.append(note)
        page.append(stats_box)
        status = payload.get("status")
        if status is not None:
            self.show_result(status, extra=f"{len(history.candles)} bars {history.period}")
        self.tab_cache["chart"] = lambda: self._on_chart_data(payload)

    def _load_fin(self, force: bool) -> None:
        page = self.pages["fin"]
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        group = None
        for name, label in (("annual", "ANNUAL"), ("quarterly", "QUARTERLY")):
            btn = Gtk.ToggleButton(label=label)
            btn.add_css_class("ft-button")
            if group is None:
                group = btn
            else:
                btn.set_group(group)
            btn.set_active(name == self.statement_period)
            btn.connect("toggled", self._on_statement_period, name)
            row.append(btn)
        page.append(row)
        self._spinner(page, f"loading statements ({self.statement_period})…")
        symbol = self.symbol
        period = self.statement_period

        def work() -> Any:
            return self.state.security.statements(symbol, period, force=force)

        self.runner.submit(work, self._on_statements)

    def _on_statement_period(self, button: Gtk.ToggleButton, name: str) -> None:
        if not button.get_active() or name == self.statement_period:
            return
        self.statement_period = name
        self._load_tab(force=True)

    def _on_statements(self, result: Any) -> None:
        page = self.pages["fin"]
        while (child := page.get_first_child()) is not None:
            page.remove(child)
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        group = None
        for name, label in (("annual", "ANNUAL"), ("quarterly", "QUARTERLY")):
            btn = Gtk.ToggleButton(label=label)
            btn.add_css_class("ft-button")
            if group is None:
                group = btn
            else:
                btn.set_group(group)
            btn.set_active(name == self.statement_period)
            btn.connect("toggled", self._on_statement_period, name)
            row.append(btn)
        page.append(row)
        if isinstance(result, Exception):
            self.set_error(str(result))
            return
        statements = result.data if result else None
        if statements is None or not statements.periods:
            label = Gtk.Label(label=f"no statements: {result.message if result else ''}", xalign=0)
            label.add_css_class("ft-err")
            page.append(label)
            return
        periods = list(reversed(statements.periods))[-5:]
        columns = [Column("label", "Metric", align="l", width=210, fmt=lambda r: r["label"])]
        for index, period in enumerate(periods):
            columns.append(
                Column(
                    f"v{index}",
                    period.date,
                    align="r",
                    fmt=_stmt_fmt(period.fields, index),
                    sort_key=lambda r, i=index: r.get(f"v{i}") if isinstance(r.get(f"v{i}"), (int, float)) else None,
                )
            )
        rows = []
        for key, label, digits in FIN_ROWS:
            record: dict[str, Any] = {"label": label, "_digits": digits}
            for index, period in enumerate(periods):
                value = period.fields.get(key)
                record[f"v{index}"] = value
            rows.append(record)
        table = DataTable(columns)
        table.set_rows(rows)
        table.set_vexpand(True)
        page.append(table)
        note = Gtk.Label(label=f"currency: {statements.currency or '?'}  ·  source: {statements.source}", xalign=0)
        note.add_css_class("ft-dim")
        page.append(note)
        self.show_result(result, extra=f"{statements.period} statements")
        self.tab_cache["fin"] = lambda: self._on_statements(result)

    def _load_val(self, force: bool) -> None:
        page = self.pages["val"]
        self._spinner(page, "loading valuation…")
        symbol = self.symbol

        def work() -> dict[str, Any]:
            valuation = self.state.security.valuation(symbol)
            model = self.state.security.dcf_model(symbol)
            return {"valuation": valuation, "model": model}

        self.runner.submit(work, self._on_valuation)

    def _on_valuation(self, payload: Any) -> None:
        page = self.pages["val"]
        while (child := page.get_first_child()) is not None:
            page.remove(child)
        if isinstance(payload, Exception):
            self.set_error(str(payload))
            return
        valuation = payload["valuation"]
        fund = valuation.data if valuation and valuation.data else None
        if fund is None:
            label = Gtk.Label(label=f"fundamentals unavailable: {valuation.message if valuation else ''}", xalign=0)
            label.add_css_class("ft-err")
            page.append(label)
            return
        fields = fund["fields"]
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=32)
        provider_grid = grid_of(
            [
                ("P/E trailing", format.num(fields.get("trailing_pe")), ""),
                ("P/E forward", format.num(fields.get("forward_pe")), ""),
                ("PEG", format.num(fields.get("peg_ratio")), ""),
                ("P/B", format.num(fields.get("price_to_book")), ""),
                ("P/S", format.num(fields.get("price_to_sales")), ""),
                ("EV/EBITDA", format.num(fields.get("ev_to_ebitda")), ""),
                ("EV/Revenue", format.num(fields.get("ev_to_revenue")), ""),
                ("Div yield", format.pct_abs(fields.get("dividend_yield")), ""),
                ("FCF", format.compact(fields.get("free_cash_flow")), ""),
            ],
            columns=1,
        )
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        head1 = Gtk.Label(label="MARKET RATIOS (provider)", xalign=0)
        head1.add_css_class("ft-section")
        left.append(head1)
        left.append(provider_grid)
        multiples = fund.get("multiples") or {}
        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        head2 = Gtk.Label(label="CALCULATED (R)", xalign=0)
        head2.add_css_class("ft-section")
        right.append(head2)
        if multiples:
            r_pairs = []
            percent_keys = {
                "dividend_yield", "roe", "roic", "gross_margin",
                "operating_margin", "net_margin", "fcf_margin",
            }
            labels = [
                ("pe", "P/E"), ("price_to_sales", "P/S"), ("price_to_book", "P/B"),
                ("ev_to_ebitda", "EV/EBITDA"), ("ev_to_sales", "EV/Revenue"),
                ("ev_to_fcf", "EV/FCF"), ("dividend_yield", "Div yield"),
                ("roe", "ROE"), ("roic", "ROIC"), ("gross_margin", "Gross margin"),
                ("operating_margin", "Op margin"), ("net_margin", "Net margin"),
                ("fcf_margin", "FCF margin"), ("debt_to_equity", "Debt/Equity"),
                ("earnings_per_share", "EPS (calc)"),
            ]
            for key, label in labels:
                if key in multiples and multiples[key] is not None:
                    value = float(multiples[key])
                    text = format.pct_abs(value) if key in percent_keys else format.num(value)
                    r_pairs.append((label, text, ""))
            if r_pairs:
                right.append(grid_of(r_pairs, columns=1))
            else:
                note = Gtk.Label(label="R returned no multiples for available inputs", xalign=0)
                note.add_css_class("ft-dim")
                right.append(note)
        else:
            note = Gtk.Label(label="R analytics unavailable", xalign=0)
            note.add_css_class("ft-warn")
            right.append(note)
        box.append(left)
        box.append(right)
        page.append(box)

        model_result = payload.get("model")
        model = model_result.data if model_result and model_result.data else None
        if model:
            head3 = Gtk.Label(label="DCF MODEL (R — assumptions below, model output, not advice)", xalign=0)
            head3.add_css_class("ft-section")
            page.append(head3)
            assumptions = model.get("assumptions") or {}
            scenario_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=24)
            result = model.get("model")
            price = assumptions.get("price")
            if isinstance(result, DcfResult):
                scenarios = {"bear": result.bear, "base": result.base, "bull": result.bull}
            elif isinstance(result, dict):
                scenarios = {key: result.get(key) or {} for key in ("bear", "base", "bull")}
            else:
                scenarios = {}
            for scenario in ("bear", "base", "bull"):
                data = scenarios.get(scenario) or {}
                if not isinstance(data, dict):
                    data = {}
                col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
                title = Gtk.Label(label=scenario.upper())
                title.add_css_class("ft-accent" if scenario == "base" else "ft-dim")
                col.append(title)
                col.append(Gtk.Label(label=f"equity {format.compact(data.get('equity_value'))}", xalign=0))
                per_share = data.get("intrinsic_value")
                col.append(Gtk.Label(label=f"per share {format.num(per_share)}", xalign=0))
                upside = None
                if per_share is not None and price:
                    try:
                        upside = float(per_share) / float(price) - 1.0
                    except (TypeError, ValueError, ZeroDivisionError):
                        upside = None
                up_label = Gtk.Label(label=f"vs price {format.pct(upside)}" if upside is not None else "vs price —")
                up_label.add_css_class(format.sign_class(upside))
                col.append(up_label)
                scenario_box.append(col)
            page.append(scenario_box)
            growth = assumptions.get("growth")
            if isinstance(growth, list):
                growth = growth[0] if growth else None
            assumption_pairs = [
                ("Revenue", format.compact(assumptions.get("revenue"))),
                ("Growth (hist CAGR)", format.pct(growth)),
                ("EBIT margin", format.pct(assumptions.get("ebit_margin"))),
                ("WACC", format.pct(assumptions.get("wacc"))),
                ("Terminal growth", format.pct(assumptions.get("terminal_growth"))),
                ("Tax rate", format.pct(assumptions.get("tax_rate"))),
                ("Capex % rev", format.pct(assumptions.get("capex_pct"))),
                ("Net debt", format.compact(assumptions.get("net_debt"))),
            ]
            page.append(grid_of([(k, v, "") for k, v in assumption_pairs], columns=4))
        elif model_result is not None:
            note = Gtk.Label(label=f"model unavailable: {model_result.message}", xalign=0)
            note.add_css_class("ft-warn")
            page.append(note)
        self.show_result(valuation)
        self.tab_cache["val"] = lambda: self._on_valuation(payload)

    def _load_risk(self, force: bool) -> None:
        page = self.pages["risk"]
        self._spinner(page, "loading risk analytics (R)…")
        symbol = self.symbol
        period = self.period

        def work() -> dict[str, Any]:
            result = self.state.market.history(symbol, period, force=force)
            payload: dict[str, Any] = {"status": result, "history": result.data}
            history = result.data
            if history is None or len(history.candles) < 30:
                return payload
            analytics = self.state.analytics
            if not analytics.available:
                return payload
            closes = [float(c.close) for c in history.candles]
            try:
                payload["stats"] = analytics.performance(closes, [format.iso_date(c.ts) for c in history.candles]).__dict__
                payload["drawdowns"] = [round(v, 6) for v in analytics.drawdowns(closes)]
                benchmark = str(self.state.portfolio.meta().get("benchmark") or "")
                if benchmark:
                    bench = self.state.market.history(benchmark, period)
                    if bench.data and len(bench.data.candles) >= 30:
                        bench_closes = [float(c.close) for c in bench.data.candles]
                        n = min(len(closes), len(bench_closes))
                        returns = [closes[i] / closes[i - 1] - 1 for i in range(1, n)]
                        bench_returns = [bench_closes[i] / bench_closes[i - 1] - 1 for i in range(1, n)]
                        payload["beta_alpha"] = analytics.beta_alpha(returns, bench_returns)
                        payload["benchmark"] = benchmark
            except Exception as exc:
                payload["r_error"] = str(exc)
                log.warning("risk analytics failed: %s", exc)
            return payload

        self.runner.submit(work, self._on_risk)

    def _on_risk(self, payload: Any) -> None:
        page = self.pages["risk"]
        while (child := page.get_first_child()) is not None:
            page.remove(child)
        if isinstance(payload, Exception):
            self.set_error(str(payload))
            return
        status = payload.get("status")
        if payload.get("history") is None:
            label = Gtk.Label(label=f"insufficient history: {status.message if status else ''}", xalign=0)
            label.add_css_class("ft-err")
            page.append(label)
            return
        stats = payload.get("stats")
        if stats:
            pairs = []
            for label in ("CAGR", "Volatility", "Sharpe", "Sortino", "Max drawdown", "Calmar", "Win rate", "VaR", "CVaR", "Skew", "Kurtosis"):
                css = format.sign_class(stats.get(label.lower().replace(" ", "_"))) if label in ("CAGR",) else ""
                pairs.append((label, _stats_value(stats, label), css))
            page.append(grid_of(pairs, columns=3))
        else:
            note = Gtk.Label(label="R unavailable — risk metrics skipped (no fabricated values)")
            note.add_css_class("ft-warn")
            page.append(note)
        beta_alpha = payload.get("beta_alpha")
        if beta_alpha:
            benchmark = payload.get("benchmark", "benchmark")
            pairs = [
                (f"Beta vs {benchmark}", format.num(beta_alpha.get("beta")), ""),
                (f"Alpha vs {benchmark}", format.pct(beta_alpha.get("alpha_annualized")), format.sign_class(beta_alpha.get("alpha_annualized"))),
                ("R²", format.num(beta_alpha.get("r_squared")), ""),
            ]
            page.append(grid_of(pairs, columns=3))
        if payload.get("r_error"):
            note = Gtk.Label(label=f"partial results: {payload['r_error']}")
            note.add_css_class("ft-warn")
            page.append(note)
        drawdowns = payload.get("drawdowns")
        if drawdowns and len(drawdowns) > 5:
            chart = Chart(height=130)
            data = ChartData(
                dates=[format.iso_date(c.ts) for c in payload["history"].candles][-len(drawdowns):],
                series=[Series("drawdown", drawdowns, theme.RED)],
                y_fmt=lambda v: f"{v * 100:.1f}%",
            )
            chart.set_data(data)
            page.append(chart)
        note = Gtk.Label(label="MODEL/STATS: computed by R worker from price history — not investment advice", xalign=0)
        note.add_css_class("ft-dim")
        page.append(note)
        if status is not None:
            self.show_result(status)
        self.tab_cache["risk"] = lambda: self._on_risk(payload)


def _fmt_stat(value: Any, kind: str) -> str:
    if value is None:
        return format.NA
    if kind == "pct":
        return format.pct(value)
    if kind == "int":
        return format.int_num(value)
    return format.num(value, 2)


def _stats_value(stats: dict[str, Any], label: str) -> str:
    key = label.lower().replace(" ", "_")
    kind = "pct" if key in (
        "cagr", "volatility", "max_drawdown", "calmar", "win_rate", "var", "cvar", "alpha"
    ) else "num"
    return _fmt_stat(stats.get(key), kind)


STAT_KEYS = [
    ("CAGR", "cagr", "pct"),
    ("VOL", "volatility", "pct"),
    ("SHARPE", "sharpe", "num"),
    ("MAXDD", "max_drawdown", "pct"),
    ("VAR 95", "var", "pct"),
]


def _stmt_fmt(fields: dict[str, float | None], index: int):
    def fmt(row: dict[str, Any]) -> str:
        value = row.get(f"v{index}")
        if value is None:
            return format.NA
        digits = row.get("_digits", 0)
        if digits:
            return format.num(value, digits)
        return format.compact(value)

    return fmt

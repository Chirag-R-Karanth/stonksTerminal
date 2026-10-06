from __future__ import annotations

from typing import Any, Callable

from data.market_hours import load_sessions, local_clock, session_status
from app.ui import format, theme
from app.ui.charts import Chart, ChartData, Series
from app.ui.gtk import Gtk
from app.ui.table import Column, DataTable
from app.ui.views.base import View, grid_of

INDEX_COLUMNS = [
    Column("symbol", "Index", align="l", width=110, fmt=lambda r: r["symbol"],
           css=lambda r: "ft-accent", sort_key=lambda r: r["symbol"]),
    Column("price", "Last", align="r", width=110, fmt=lambda r: format.num(r.get("price")),
           sort_key=lambda r: r.get("price") or 0),
    Column("change_pct", "Chg %", align="r", width=100, fmt=lambda r: format.pct(r.get("change_pct")),
           css=lambda r: format.sign_class(r.get("change_pct")),
           sort_key=lambda r: r.get("change_pct") if r.get("change_pct") is not None else -999),
    Column("status", "Session", align="l", width=110, fmt=lambda r: r.get("session", "")),
    Column("error", "Note", align="l", fmt=lambda r: r.get("error", ""), css=lambda r: "ft-err" if r.get("error") else ""),
]

NEWS_COLUMNS = [
    Column("time", "Time", align="l", width=120, fmt=lambda r: r.get("time", "")),
    Column("source", "Source", align="l", width=110, fmt=lambda r: r.get("source", "")),
    Column("title", "Headline", align="l", fmt=lambda r: r.get("title", "")),
]


class MarketsView(View):
    view_name = "markets"

    def __init__(self, state: Any, runner: Any, open_panel: Callable[..., None] | None = None):
        super().__init__(state, runner, open_panel)
        self.symbols = [str(s) for s in state.config.get("markets.indices", []) or []]

    def mount(self, payload: dict[str, Any]) -> None:
        self.set_title("MARKETS — indices, rates, sessions, headlines")
        super().mount(payload)

    def load(self, force: bool = False) -> None:
        symbols = list(self.symbols)
        self.set_busy("loading markets…")

        def work():
            quotes = self.state.market.quotes(symbols, force=force)
            curve = self.state.macro.yield_curve(force=force)
            news = self.state.news.rows(limit=int(self.state.config.get("markets.headline_count", 8)), force=force)
            return {"quotes": quotes, "curve": curve, "news": news}

        self.runner.submit(work, self._on_data)

    def _on_data(self, payload: Any) -> None:
        if isinstance(payload, Exception):
            self.set_error(str(payload))
            return
        self.clear_content()
        sessions = load_sessions(self.state.config)

        clocks = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=18)
        for session in sessions:
            status = session_status(session)
            item = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            name = Gtk.Label(label=session.exchange)
            name.add_css_class("ft-dim")
            clock = Gtk.Label(label=local_clock(session))
            state_label = Gtk.Label(label=status)
            state_label.add_css_class(
                "ft-up" if status == "OPEN" else ("ft-warn" if status in ("PRE-MARKET", "AFTER-HOURS") else "ft-dim")
            )
            item.append(name)
            item.append(clock)
            item.append(state_label)
            clocks.append(item)
        self.content.append(clocks)

        rows = []
        for symbol in self.symbols:
            result = payload["quotes"].get(symbol)
            quote = result.data if result else None
            rows.append(
                {
                    "symbol": symbol,
                    "price": quote.price if quote else None,
                    "change_pct": quote.change_pct if quote else None,
                    "session": _session_for(symbol, sessions),
                    "error": (result.message or "")[:60] if result and not result.ok else "",
                }
            )
        table = DataTable(
            INDEX_COLUMNS,
            on_activate=lambda row: self.open_panel({"view": "security", "symbol": row["symbol"], "action": "chart"})
            if self.open_panel
            else None,
        )
        table.set_rows(rows)
        self.content.append(table)

        curve = payload.get("curve")
        if curve and curve.data:
            points = curve.data["points"]
            if len(points) >= 2:
                head = Gtk.Label(label=f"US TREASURY YIELD CURVE  ({points[0]['date']})", xalign=0)
                head.add_css_class("ft-section")
                self.content.append(head)
                chart = Chart(height=150)
                chart.set_data(
                    ChartData(
                        dates=[f"{p['tenor']}Y" for p in points],
                        series=[Series("yield", [float(p["value"]) for p in points], theme.CYAN)],
                        y_fmt=lambda v: f"{v:.2f}%",
                    )
                )
                self.content.append(chart)

        news = payload.get("news")
        if news is not None and news.data:
            head = Gtk.Label(label="HEADLINES", xalign=0)
            head.add_css_class("ft-section")
            self.content.append(head)
            news_table = DataTable(
                NEWS_COLUMNS,
                on_activate=lambda row: self.open_url(str(row.get("url") or "")),
            )
            news_table.set_rows(news.data)
            self.content.append(news_table)

        statuses = [r.status for r in payload["quotes"].values() if r]
        worst = "live"
        for status in statuses:
            if status in ("error", "offline"):
                worst = status
            elif status == "stale" and worst == "live":
                worst = "stale"
        from data.models import DataResult

        self.show_result(
            DataResult(data=rows, status=worst if statuses else "error", provider=self.state.market.name),
            extra=f"{len(rows)} indices",
        )


def _session_for(symbol: str, sessions: list) -> str:
    from data.market_hours import symbol_session_status

    return symbol_session_status(symbol, sessions)

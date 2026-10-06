from __future__ import annotations

from typing import Any, Callable

from app.commands.parser import ParseError, parse
from app.ui import format
from app.ui.gtk import Gtk
from app.ui.table import Column, DataTable
from app.ui.views.base import View

RESULT_COLUMNS = [
    Column("symbol", "Symbol", align="l", width=110, fmt=lambda r: r.get("symbol", ""),
           css=lambda r: "ft-accent", sort_key=lambda r: r.get("symbol", "")),
    Column("name", "Name", align="l", fmt=lambda r: r.get("name") or format.NA,
           sort_key=lambda r: r.get("name") or ""),
    Column("sector", "Sector", align="l", width=150, fmt=lambda r: r.get("sector") or format.NA,
           sort_key=lambda r: r.get("sector") or ""),
    Column("market_cap", "Mkt Cap", align="r", width=100, fmt=lambda r: format.compact(r.get("market_cap")),
           sort_key=lambda r: r.get("market_cap") or 0),
    Column("trailing_pe", "P/E", align="r", width=80, fmt=lambda r: format.num(r.get("trailing_pe")),
           sort_key=lambda r: r.get("trailing_pe") if r.get("trailing_pe") is not None else -1),
    Column("forward_pe", "Fwd P/E", align="r", width=85, fmt=lambda r: format.num(r.get("forward_pe")),
           sort_key=lambda r: r.get("forward_pe") if r.get("forward_pe") is not None else -1),
    Column("price_to_book", "P/B", align="r", width=75, fmt=lambda r: format.num(r.get("price_to_book")),
           sort_key=lambda r: r.get("price_to_book") if r.get("price_to_book") is not None else -1),
    Column("roe", "ROE", align="r", width=80, fmt=lambda r: format.pct(r.get("roe")),
           css=lambda r: format.sign_class(r.get("roe")),
           sort_key=lambda r: r.get("roe") if r.get("roe") is not None else -1),
    Column("profit_margin", "Margin", align="r", width=85, fmt=lambda r: format.pct(r.get("profit_margin")),
           sort_key=lambda r: r.get("profit_margin") if r.get("profit_margin") is not None else -1),
    Column("debt_to_equity", "D/E", align="r", width=80, fmt=lambda r: format.num(r.get("debt_to_equity")),
           sort_key=lambda r: r.get("debt_to_equity") if r.get("debt_to_equity") is not None else -1),
    Column("dividend_yield", "Yield", align="r", width=75, fmt=lambda r: format.pct(r.get("dividend_yield")),
           sort_key=lambda r: r.get("dividend_yield") if r.get("dividend_yield") is not None else -1),
    Column("revenue_growth", "Growth", align="r", width=85, fmt=lambda r: format.pct(r.get("revenue_growth")),
           css=lambda r: format.sign_class(r.get("revenue_growth")),
           sort_key=lambda r: r.get("revenue_growth") if r.get("revenue_growth") is not None else -1),
]


class ScreenerView(View):
    view_name = "screener"

    def __init__(self, state: Any, runner: Any, open_panel: Callable[..., None] | None = None):
        super().__init__(state, runner, open_panel)
        self.filters_text = ""
        self.autorun = False
        self.results: list[dict[str, Any]] = []
        self.pending = False

        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.entry = Gtk.Entry()
        self.entry.add_css_class("ft-prompt-entry")
        self.entry.set_hexpand(True)
        self.entry.set_placeholder_text("PE<20 ROE>0.15 MARKETCAP>2e10   (HELP FILTERS for fields)")
        self.entry.connect("activate", self._on_run)
        bar.append(self.entry)
        run_btn = Gtk.Button(label="RUN")
        run_btn.add_css_class("ft-button")
        run_btn.connect("clicked", self._on_run)
        bar.append(run_btn)
        save_btn = Gtk.Button(label="SAVE")
        save_btn.add_css_class("ft-button")
        save_btn.set_tooltip_text("SCREEN SAVE <name> <filters>")
        save_btn.connect("clicked", self._on_save)
        bar.append(save_btn)
        self.content.append(bar)

        self.hint = Gtk.Label(label="", xalign=0)
        self.hint.add_css_class("ft-dim")
        self.content.append(self.hint)

        self.table = DataTable(
            RESULT_COLUMNS,
            on_activate=lambda row: self.open_panel({"view": "security", "symbol": row.get("symbol", ""), "action": "overview"})
            if self.open_panel
            else None,
        )
        self.table.set_vexpand(True)
        self.content.append(self.table)

    def mount(self, payload: dict[str, Any]) -> None:
        self.set_title("SCREENER — fundamental screens over local + universe cache")
        filters = payload.get("filters")
        if filters is not None:
            self.filters_text = str(filters)
            self.entry.set_text(self.filters_text)
        self.autorun = bool(payload.get("autorun", self.autorun))
        super().mount(payload)

    def _on_save(self, _btn: Gtk.Button) -> None:
        text = self.entry.get_text().strip()
        if not text:
            self.hint.set_text("nothing to save — enter filters first")
            return
        self.hint.set_text(f'to save: SCREEN SAVE <name> {text}')

    def _on_run(self, *_args: Any) -> None:
        self.filters_text = self.entry.get_text().strip()
        self.load(force=True)

    def load(self, force: bool = False) -> None:
        text = self.filters_text
        if not text and not self.autorun:
            self.table.set_rows([])
            self.hint.set_text("enter filters, e.g. PE<20 ROE>0.15 · or run: SCREEN LOAD <name>")
            self.set_status([("READY", "ft-dim")])
            return
        self.autorun = False
        if not text:
            self.table.set_rows([])
            self.hint.set_text("no filters — try PE<20 ROE>0.15")
            return
        try:
            command = parse(f"SCREEN {text}")
        except ParseError as exc:
            self.set_error(str(exc))
            return
        if command.verb != "SCREEN" or not command.filters:
            self.set_error(f"could not parse filters: {text}")
            return
        filters = [
            {"field": f.field, "op": f.op, "value": f.value, "raw": f.raw} for f in command.filters
        ]
        self.set_busy(f"screening {len(self.state.screener.universe())} symbols (first run fetches data)…")
        self.hint.set_text(" · ".join(f["raw"] for f in filters))

        def work():
            return self.state.screener.run(filters, limit=100, force=force)

        self.runner.submit(work, self._on_result)

    def _on_result(self, result: Any) -> None:
        if isinstance(result, Exception):
            self.set_error(str(result))
            return
        rows = result.data or []
        self.results = rows
        self.table.set_rows(rows)
        self.show_result(result, extra=f"{len(rows)} matches  ·  click row for detail")

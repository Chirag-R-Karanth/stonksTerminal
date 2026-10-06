from __future__ import annotations

from typing import Any, Callable

from app.ui import format
from app.ui.gtk import Gtk
from app.ui.table import Column, DataTable
from app.ui.views.base import View

COLUMNS = [
    Column("symbol", "Symbol", align="l", width=110, fmt=lambda r: r["symbol"],
           css=lambda r: "ft-accent", sort_key=lambda r: r["symbol"]),
    Column("name", "Name", align="l", fmt=lambda r: r.get("name") or format.NA,
           sort_key=lambda r: r.get("name") or ""),
    Column("price", "Last", align="r", width=100,
           fmt=lambda r: format.num(r.get("price")), sort_key=lambda r: r.get("price") or 0),
    Column("change_pct", "Chg %", align="r", width=90,
           fmt=lambda r: format.pct(r.get("change_pct")),
           css=lambda r: format.sign_class(r.get("change_pct")),
           sort_key=lambda r: r.get("change_pct") if r.get("change_pct") is not None else -999),
    Column("market_cap", "Mkt Cap", align="r", width=90,
           fmt=lambda r: format.compact(r.get("market_cap")), sort_key=lambda r: r.get("market_cap") or 0),
    Column("currency", "Cur", align="l", width=50, fmt=lambda r: r.get("currency") or ""),
    Column("status", "Status", align="l", width=90,
           fmt=lambda r: r.get("status", ""), css=lambda r: _status_css(r.get("status"))),
]


def _status_css(status: str | None) -> str:
    return {
        "live": "ft-up",
        "cached": "ft-dim",
        "stale": "ft-warn",
        "error": "ft-err",
        "offline": "ft-err",
    }.get(status or "", "ft-dim")


class WatchlistView(View):
    view_name = "watchlist"

    def __init__(self, state: Any, runner: Any, open_panel: Callable[..., None] | None = None):
        super().__init__(state, runner, open_panel)
        self.list_name = ""
        self.table = DataTable(COLUMNS, on_activate=self._activate)
        self.content.append(self.table)
        self.table.set_vexpand(True)

    def mount(self, payload: dict[str, Any]) -> None:
        name = str(payload.get("list") or "")
        if not name:
            name = self.state.watchlists.ensure()
        self.list_name = name
        self.set_title(f"WATCHLIST  {name}")
        super().mount(payload)

    def _activate(self, row: dict[str, Any]) -> None:
        if self.open_panel:
            self.open_panel({"view": "security", "symbol": row.get("symbol", ""), "action": "overview"})

    def load(self, force: bool = False) -> None:
        name = self.list_name
        if not name:
            return
        self.set_busy(f"loading {name}…")

        def work():
            return self.state.watchlists.rows(name, force=force)

        self.runner.submit(work, self._on_rows)

    def _on_rows(self, result: Any) -> None:
        if isinstance(result, Exception):
            self.set_error(str(result))
            return
        if isinstance(result, KeyError):
            self.set_error(str(result))
            return
        rows = result or []
        self.table.set_rows(rows)
        statuses = {row.get("status") for row in rows}
        if "error" in statuses and len(statuses) == 1:
            status = "error"
        elif "live" in statuses:
            status = "live"
        elif "stale" in statuses:
            status = "stale"
        elif statuses:
            status = sorted(statuses)[0]
        else:
            status = "cached"
        from data.models import DataResult

        shown = DataResult(
            data=rows,
            status=status,
            provider=self.state.market.name,
            message=", ".join(sorted(s for s in statuses if s in ("error", "stale"))) or "",
        )
        self.show_result(shown, extra=f"{len(rows)} symbols")

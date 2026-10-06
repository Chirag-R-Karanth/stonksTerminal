from __future__ import annotations

from typing import Any, Callable

from app.ui import format
from app.ui.gtk import Gtk
from app.ui.table import Column, DataTable
from app.ui.views.base import View

COLUMNS = [
    Column("time", "Time", align="l", width=120, fmt=lambda r: r.get("time", ""),
           sort_key=lambda r: r.get("time", "")),
    Column("source", "Source", align="l", width=120, fmt=lambda r: r.get("source", ""),
           sort_key=lambda r: r.get("source", "")),
    Column("title", "Headline", align="l", fmt=lambda r: r.get("title", ""),
           sort_key=lambda r: r.get("title", "")),
    Column("symbols", "Symbols", align="l", width=140, fmt=lambda r: r.get("symbols", ""),
           css=lambda r: "ft-accent" if r.get("symbols") else ""),
]


class NewsView(View):
    view_name = "news"

    def __init__(self, state: Any, runner: Any, open_panel: Callable[..., None] | None = None):
        super().__init__(state, runner, open_panel)
        self.symbols: list[str] = []
        self.query: str | None = None
        self.rows: list[dict[str, Any]] = []
        self.table = DataTable(COLUMNS, on_activate=self._activate)
        self.table.set_vexpand(True)
        self.content.append(self.table)

    def mount(self, payload: dict[str, Any]) -> None:
        symbols = payload.get("symbols")
        query = payload.get("query")
        if symbols is not None:
            self.symbols = [str(s).upper() for s in symbols]
        if query is not None:
            self.query = str(query) if query else None
        title = "NEWS"
        if self.symbols:
            title += "  " + ", ".join(self.symbols)
        if self.query:
            title += f'  "{self.query}"'
        self.set_title(title)
        super().mount(payload)

    def _activate(self, row: dict[str, Any]) -> None:
        self.open_url(str(row.get("url") or ""))

    def load(self, force: bool = False) -> None:
        symbols = list(self.symbols)
        query = self.query
        self.set_busy("loading headlines…")

        def work():
            return self.state.news.rows(symbols=symbols or None, query=query, limit=80, force=force)

        self.runner.submit(work, self._on_rows)

    def _on_rows(self, result: Any) -> None:
        if isinstance(result, Exception):
            self.set_error(str(result))
            return
        rows = result.data or []
        self.rows = rows
        self.table.set_rows(rows)
        self.show_result(result, extra=f"{len(rows)} headlines  ·  click row to open")

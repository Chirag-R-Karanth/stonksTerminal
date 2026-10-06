from __future__ import annotations

from typing import Any, Callable

from app.ui import format, theme
from app.ui.charts import Chart, ChartData, Series
from app.ui.gtk import Gtk
from app.ui.table import Column, DataTable
from app.ui.views.base import View, grid_of

CATALOG_COLUMNS = [
    Column("key", "Key", align="l", width=130, fmt=lambda r: r["key"], sort_key=lambda r: r["key"]),
    Column("title", "Series", align="l", fmt=lambda r: r.get("title", ""), sort_key=lambda r: r.get("title", "")),
    Column("series", "FRED id", align="l", width=110, fmt=lambda r: r.get("series", "")),
    Column("latest", "Latest", align="r", width=110, fmt=lambda r: r.get("latest", ""),
           sort_key=lambda r: r.get("_latest") if r.get("_latest") is not None else -1e18),
    Column("date", "Date", align="l", width=110, fmt=lambda r: r.get("date", "")),
    Column("units", "Units", align="l", width=120, fmt=lambda r: r.get("units", "")),
]

OBS_COLUMNS = [
    Column("date", "Date", align="l", width=120, fmt=lambda r: r["date"], sort_key=lambda r: r["date"]),
    Column("value", "Value", align="r", width=120, fmt=lambda r: format.num(r.get("value"), 3),
           sort_key=lambda r: r.get("value") if r.get("value") is not None else -1e18),
]


class MacroView(View):
    view_name = "macro"

    def __init__(self, state: Any, runner: Any, open_panel: Callable[..., None] | None = None):
        super().__init__(state, runner, open_panel)
        self.series_key: str | None = None

    def mount(self, payload: dict[str, Any]) -> None:
        key = payload.get("series")
        self.series_key = str(key).upper() if key else None
        if self.series_key:
            self.set_title(f"MACRO  {self.series_key}")
        else:
            self.set_title("MACRO — economic series & yield curve")
        super().mount(payload)

    def load(self, force: bool = False) -> None:
        key = self.series_key
        self.set_busy("loading macro data…")

        def work():
            if key:
                return {"series": self.state.macro.series(key, force=force), "catalog": self.state.macro.catalog()}
            return {"curve": self.state.macro.yield_curve(force=force), "catalog": self.state.macro.catalog(),
                    "series_map": {c["key"]: self.state.macro.series(c["key"], force=force) for c in self.state.macro.catalog()}}

        self.runner.submit(work, self._on_data)

    def _on_data(self, payload: Any) -> None:
        if isinstance(payload, Exception):
            self.set_error(str(payload))
            return
        self.clear_content()
        if self.series_key:
            self._render_series(payload)
        else:
            self._render_overview(payload)

    def _series_nav(self) -> Gtk.Box:
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        head = Gtk.Label(label="series:")
        head.add_css_class("ft-dim")
        box.append(head)
        for entry in self.state.macro.catalog():
            btn = Gtk.Button(label=entry["key"])
            btn.add_css_class("ft-button")
            btn.connect(
                "clicked",
                lambda *_b, k=entry["key"]: self.open_panel({"view": "macro", "series": k})
                if self.open_panel
                else None,
            )
            box.append(btn)
        if self.series_key:
            back = Gtk.Button(label="OVERVIEW")
            back.add_css_class("ft-button")
            back.connect("clicked", lambda *_b: self.open_panel({"view": "macro"}) if self.open_panel else None)
            box.append(back)
        return box

    def _render_series(self, payload: dict[str, Any]) -> None:
        self.content.append(self._series_nav())
        result = payload.get("series")
        data = result.data if result else None
        if data is None:
            self.set_error(result.message if result else "no data")
            return
        chart = Chart(height=260)
        chart_data = ChartData(
            dates=[o.date for o in data.observations],
            series=[Series(data.title or data.id, [o.value for o in data.observations], theme.CYAN)],
            y_fmt=lambda v: f"{v:,.2f}",
        )
        chart.set_data(chart_data)
        self.content.append(chart)
        latest = self.state.macro.latest(data) if data.observations else None
        if latest:
            grid = grid_of(
                [
                    ("Latest", format.num(latest[1], 3), "ft-accent"),
                    ("Date", latest[0], ""),
                    ("Units", data.units or "?", ""),
                    ("Observations", format.int_num(len(data.observations)), ""),
                ],
                columns=4,
            )
            self.content.append(grid)
        rows = [{"date": o.date, "value": o.value} for o in reversed(data.observations[-40:])]
        table = DataTable(OBS_COLUMNS)
        table.set_rows(rows)
        self.content.append(table)
        self.show_result(result, extra=data.title)

    def _render_overview(self, payload: dict[str, Any]) -> None:
        curve = payload.get("curve")
        self.content.append(self._series_nav())
        if curve and curve.data:
            points = curve.data.get("points", [])
            if len(points) >= 2:
                chart = Chart(height=170)
                chart_data = ChartData(
                    dates=[f"{p['tenor']}Y" for p in points],
                    series=[Series("yield curve", [float(p["value"]) for p in points], theme.AMBER)],
                    y_fmt=lambda v: f"{v:.2f}%",
                )
                chart.set_data(chart_data)
                head = Gtk.Label(label=f"US TREASURY YIELD CURVE  ({points[0]['date']})", xalign=0)
                head.add_css_class("ft-section")
                self.content.append(head)
                self.content.append(chart)
        elif curve is not None:
            note = Gtk.Label(label=f"yield curve unavailable: {curve.message}", xalign=0)
            note.add_css_class("ft-warn")
            self.content.append(note)
        head2 = Gtk.Label(label="SERIES", xalign=0)
        head2.add_css_class("ft-section")
        self.content.append(head2)
        series_map = payload.get("series_map") or {}
        rows = []
        worst = "live"
        first_result = None
        for entry in payload.get("catalog", []):
            result = series_map.get(entry["key"])
            if result is not None:
                first_result = first_result or result
                if not result.ok:
                    worst = "error"
                elif result.status in ("stale", "cached") and worst == "live":
                    worst = result.status
            latest = ("", None)
            if result and result.data and result.data.observations:
                obs = result.data.observations[-1]
                latest = (obs.date, obs.value)
            rows.append(
                {
                    "key": entry["key"],
                    "title": entry["title"],
                    "series": entry["series"],
                    "latest": format.num(latest[1], 3) if latest[1] is not None else format.NA,
                    "_latest": latest[1],
                    "date": latest[0] or "",
                    "units": entry.get("units", ""),
                }
            )
        table = DataTable(
            CATALOG_COLUMNS,
            on_activate=lambda row: self.open_panel({"view": "macro", "series": row["key"]})
            if self.open_panel
            else None,
        )
        table.set_rows(rows)
        self.content.append(table)
        if first_result is not None:
            from data.models import DataResult

            self.show_result(
                DataResult(data=rows, status=worst, provider=first_result.provider,
                           message=first_result.message if worst == "error" else ""),
                extra=f"{len(rows)} series",
            )

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from app.ui.gtk import Gdk, Gtk, Pango

from app.ui import theme

Row = dict[str, Any]


@dataclass
class Column:
    key: str
    title: str
    align: str = "l"
    width: int = 0
    fmt: Callable[[Row], str] = lambda row: str(row.get("", ""))
    css: Callable[[Row], str] = lambda row: ""
    sort_key: Callable[[Row], Any] | None = None


class DataTable(Gtk.Box):
    def __init__(
        self,
        columns: list[Column],
        on_activate: Callable[[Row], None] | None = None,
        row_height: int = 22,
    ):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.columns = columns
        self.on_activate = on_activate
        self.row_height = row_height
        self.rows: list[Row] = []
        self.sort_column: Column | None = None
        self.sort_desc = True
        self.add_css_class("ft-scroll")

        self.header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        self.header.add_css_class("ft-table-header")
        for column in columns:
            btn = Gtk.Button(label=column.title)
            btn.add_css_class("ft-button")
            btn.set_hexpand(column.width == 0)
            if column.width:
                btn.set_size_request(column.width, -1)
            btn.connect("clicked", self._on_header, column)
            self.header.append(btn)
        self.append(self.header)

        self.body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.scroller = Gtk.ScrolledWindow()
        self.scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        self.scroller.set_vexpand(True)
        self.scroller.set_child(self.body)
        self.scroller.add_css_class("ft-scroll")
        self.append(self.scroller)

        self.placeholder = Gtk.Label(label="(no rows)")
        self.placeholder.add_css_class("ft-dim")
        self.body.append(self.placeholder)

    def set_columns(self, columns: list[Column]) -> None:
        self.columns = columns
        while (child := self.header.get_first_child()) is not None:
            self.header.remove(child)
        for column in columns:
            btn = Gtk.Button(label=column.title)
            btn.add_css_class("ft-button")
            btn.set_hexpand(column.width == 0)
            if column.width:
                btn.set_size_request(column.width, -1)
            btn.connect("clicked", self._on_header, column)
            self.header.append(btn)

    def _on_header(self, _btn: Gtk.Button, column: Column) -> None:
        if self.sort_column is column:
            self.sort_desc = not self.sort_desc
        else:
            self.sort_column = column
            self.sort_desc = True
        self._render()

    def set_rows(self, rows: list[Row]) -> None:
        self.rows = rows
        self._render()

    def _sorted(self) -> list[Row]:
        column = self.sort_column
        if column is None:
            return list(self.rows)
        key = column.sort_key or (lambda row: row.get(column.key))
        try:
            return sorted(
                self.rows,
                key=lambda row: (key(row) is None, key(row) if key(row) is not None else 0),
                reverse=self.sort_desc,
            )
        except TypeError:
            return list(self.rows)

    def _render(self) -> None:
        while (child := self.body.get_first_child()) is not None:
            self.body.remove(child)
        rows = self._sorted()
        if not rows:
            self.placeholder = Gtk.Label(label="(no rows)")
            self.placeholder.add_css_class("ft-dim")
            self.body.append(self.placeholder)
            return
        for index, row in enumerate(rows):
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
            box.add_css_class("ft-row")
            if index % 2:
                box.add_css_class("ft-row-alt")
            box.set_size_request(-1, self.row_height)
            for column in self.columns:
                label = Gtk.Label(xalign=0.0 if column.align == "l" else 1.0)
                label.set_text(column.fmt(row))
                label.set_ellipsize(Pango.EllipsizeMode.END)
                label.set_margin_start(6)
                label.set_margin_end(6)
                label.set_hexpand(column.width == 0)
                if column.width:
                    label.set_size_request(column.width, -1)
                css = column.css(row)
                if css:
                    label.add_css_class(css)
                box.append(label)
            gesture = Gtk.GestureClick()
            gesture.connect("released", self._on_row_click, row)
            box.add_controller(gesture)
            self.body.append(box)

    def _on_row_click(self, gesture: Gtk.GestureClick, _n: int, _x: float, _y: float, row: Row) -> None:
        if gesture.get_current_button() == Gdk.BUTTON_PRIMARY and self.on_activate:
            self.on_activate(row)

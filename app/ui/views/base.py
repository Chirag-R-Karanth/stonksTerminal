from __future__ import annotations

import logging
from typing import Any, Callable

from app.ui import format, theme
from app.ui.async_runner import AsyncRunner
from app.ui.gtk import Gtk
from data.models import DataResult

log = logging.getLogger(__name__)


class View(Gtk.Box):
    view_name = "base"
    title_text = ""

    def __init__(
        self,
        state: Any,
        runner: AsyncRunner,
        open_panel: Callable[[dict[str, Any]], None] | None = None,
    ):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.state = state
        self.runner = runner
        self.open_panel = open_panel
        self.payload: dict[str, Any] = {}
        self.set_margin_start(8)
        self.set_margin_end(8)
        self.set_margin_top(6)
        self.set_margin_bottom(6)

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.title_label = Gtk.Label(label=self.title_text, xalign=0)
        self.title_label.add_css_class("ft-title")
        self.title_label.set_hexpand(True)
        header.append(self.title_label)
        self.refresh_btn = Gtk.Button(label="⟳")
        self.refresh_btn.add_css_class("ft-button")
        self.refresh_btn.set_tooltip_text("refresh (Ctrl+R)")
        self.refresh_btn.connect("clicked", lambda *_: self.refresh(force=True))
        header.append(self.refresh_btn)
        self.append(header)

        self.status_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.status_box.set_margin_top(2)
        self.append(self.status_box)

        self.content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.content.set_vexpand(True)
        self.append(self.content)

    def set_title(self, text: str) -> None:
        self.title_text = text
        self.title_label.set_text(text)

    def set_status(self, bits: list[tuple[str, str]]) -> None:
        while (child := self.status_box.get_first_child()) is not None:
            self.status_box.remove(child)
        for text, css in bits:
            label = Gtk.Label(label=text, xalign=0)
            if css:
                label.add_css_class(css)
            self.status_box.append(label)

    def show_result(self, result: DataResult | None, extra: str = "") -> None:
        if result is None:
            self.set_status([("", "")])
            return
        bits = format.status_bits(result.status, result.provider, result.fetched_at)
        if result.is_demo:
            bits.append(("DEMO DATA — NOT REAL MARKET DATA", "ft-warn"))
        if extra:
            bits.append((extra, "ft-dim"))
        if result.message:
            bits.append((result.message[:160], "ft-err" if not result.ok else "ft-warn"))
        self.set_status(bits)

    def set_error(self, text: str) -> None:
        self.set_status([("ERROR", "ft-err"), (text, "ft-err")])

    def set_busy(self, text: str = "loading…") -> None:
        self.set_status([(text, "ft-dim")])

    def mount(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.load(force=False)

    def refresh(self, force: bool = True) -> None:
        self.load(force=force)

    def load(self, force: bool = False) -> None:
        raise NotImplementedError

    def clear_content(self) -> None:
        while (child := self.content.get_first_child()) is not None:
            self.content.remove(child)

    def open_url(self, url: str) -> None:
        if not url:
            return
        try:
            import shutil
            import subprocess

            if shutil.which("xdg-open"):
                subprocess.Popen(["xdg-open", url])
        except Exception as exc:
            log.warning("open url failed: %s", exc)


def labeled_value(label: str, value: str, css: str = "") -> tuple[Gtk.Box, Gtk.Label]:
    box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
    key = Gtk.Label(label=label, xalign=0)
    key.add_css_class("ft-dim")
    key.set_width_chars(18)
    val = Gtk.Label(label=value, xalign=0)
    if css:
        val.add_css_class(css)
    box.append(key)
    box.append(val)
    return box, val


def grid_of(pairs: list[tuple[str, str, str]], columns: int = 2) -> Gtk.Grid:
    grid = Gtk.Grid()
    grid.set_column_homogeneous(False)
    grid.set_row_spacing(2)
    grid.set_column_spacing(24)
    for index, (label, value, css) in enumerate(pairs):
        row, col = divmod(index, columns)
        box, _ = labeled_value(label, value, css)
        grid.attach(box, col, row, 1, 1)
    return grid

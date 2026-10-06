from __future__ import annotations

from app.ui import theme
from app.ui.gtk import Gtk, Pango


class ConsoleLog(Gtk.Box):
    def __init__(self, height: int = 150):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.set_size_request(-1, height)
        self.view = Gtk.TextView()
        self.view.set_editable(False)
        self.view.set_cursor_visible(False)
        self.view.set_monospace(True)
        self.view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.view.set_left_margin(6)
        self.view.set_top_margin(4)
        self.view.add_css_class("ft-log")
        self.view.set_size_request(-1, height)

        buffer = self.view.get_buffer()
        for name, color in (
            ("err", theme.RED),
            ("warn", theme.YELLOW),
            ("dim", theme.DIM),
            ("cmd", theme.AMBER),
            ("ok", theme.GREEN),
            ("info", theme.FG),
        ):
            tag = buffer.create_tag(name)
            tag.set_property("foreground", color)

        self.scroller = Gtk.ScrolledWindow()
        self.scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        self.scroller.set_child(self.view)
        self.scroller.set_vexpand(True)
        Gtk.Box.append(self, self.scroller)

    def append(self, text: str, tag: str = "info") -> None:
        if not text:
            return
        buffer = self.view.get_buffer()
        end = buffer.get_end_iter()
        buffer.insert_with_tags_by_name(end, text + "\n", tag)
        self._scroll_end()

    def append_rich(self, text: str, tags: list[str]) -> None:
        buffer = self.view.get_buffer()
        end = buffer.get_end_iter()
        buffer.insert_with_tags_by_name(end, text + "\n", *tags)
        self._scroll_end()

    def clear(self) -> None:
        buffer = self.view.get_buffer()
        buffer.set_text("")

    def _scroll_end(self) -> None:
        adjustment = self.scroller.get_vadjustment()
        adjustment.set_value(adjustment.get_upper() - adjustment.get_page_size())

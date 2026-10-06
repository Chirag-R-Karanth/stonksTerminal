from __future__ import annotations

import logging
from typing import Callable

from app.ui import theme
from app.ui.gtk import Gdk, GObject, Gtk

log = logging.getLogger(__name__)

RETURN_KEYS = (Gdk.KEY_Return, Gdk.KEY_KP_Enter, Gdk.KEY_ISO_Enter)


class Prompt(Gtk.Box):
    __gsignals__ = {
        "run": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
    }

    def __init__(self, suggest_fn: Callable[[str], list[str]], history_fn: Callable[[], list[str]]):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.suggest_fn = suggest_fn
        self.history_fn = history_fn
        self.add_css_class("ft-header")

        self.label = Gtk.Label(label="FT>", xalign=0)
        self.label.add_css_class("ft-accent")
        self.append(self.label)

        self.entry = Gtk.Entry()
        self.entry.add_css_class("ft-prompt-entry")
        self.entry.set_hexpand(True)
        self.entry.set_placeholder_text("type a command or symbol  ·  TAB completes  ·  F1 help")
        self.entry.connect("changed", self._on_changed)
        key = Gtk.EventControllerKey()
        key.connect("key-pressed", self._on_key)
        self.entry.add_controller(key)
        self.append(self.entry)

        self.listbox = Gtk.ListBox()
        self.listbox.add_css_class("ft-completion")
        self.listbox.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.listbox.connect("row-activated", self._on_row_activated)
        self.popover = Gtk.Popover()
        self.popover.set_child(self.listbox)
        self.popover.set_parent(self.entry)
        self.popover.set_autohide(True)
        self.popover.set_position(Gtk.PositionType.BOTTOM)
        self.suggestions: list[str] = []
        self._history: list[str] = []
        self._history_index: int | None = None
        self._draft = ""

    def focus(self) -> None:
        self.entry.grab_focus()

    def set_text(self, text: str) -> None:
        self.entry.set_text(text)
        self.entry.set_position(len(text))

    def text(self) -> str:
        return self.entry.get_text()

    def _on_changed(self, _entry: Gtk.Entry) -> None:
        text = self.entry.get_text()
        try:
            self.suggestions = self.suggest_fn(text)[:10]
        except Exception as exc:
            log.warning("suggest failed: %s", exc)
            self.suggestions = []
        self._show_suggestions()

    def _show_suggestions(self) -> None:
        while (child := self.listbox.get_first_child()) is not None:
            self.listbox.remove(child)
        if not self.suggestions:
            self.popover.popdown()
            return
        for suggestion in self.suggestions:
            row = Gtk.ListBoxRow()
            label = Gtk.Label(label=suggestion, xalign=0)
            label.add_css_class("ft-dim")
            row.set_child(label)
            self.listbox.append(row)
        self.listbox.select_row(self.listbox.get_row_at_index(0))
        if not self.popover.get_visible():
            self.popover.popup()

    def _accept(self, text: str) -> None:
        self.popover.popdown()
        self.set_text(text)
        self.entry.grab_focus()

    def _complete_prefix(self) -> None:
        if not self.suggestions:
            return
        common = _common_prefix([s.rstrip() for s in self.suggestions])
        current = self.entry.get_text()
        if common and len(common) > len(current):
            self._accept(common)
            return
        self._accept(self.suggestions[0])

    def _load_history(self) -> None:
        try:
            self._history = self.history_fn()
        except Exception as exc:
            log.warning("history load failed: %s", exc)
            self._history = []

    def _history_move(self, delta: int) -> None:
        if self._history_index is None:
            self._load_history()
            if not self._history:
                return
            self._draft = self.entry.get_text()
            self._history_index = 0 if delta > 0 else len(self._history) - 1
        else:
            self._history_index += delta
        if self._history_index < 0:
            self._history_index = 0
        if self._history_index >= len(self._history):
            self._history_index = None
            self.set_text(self._draft)
            return
        self.set_text(self._history[self._history_index])

    def _run(self) -> None:
        text = self.entry.get_text().strip()
        if not text:
            return
        self.popover.popdown()
        self._history_index = None
        self.emit("run", text)
        self.set_text("")

    def _on_key(self, _ctrl: Gtk.EventControllerKey, keyval: int, _code: int, mods: int) -> bool:
        ctrl = bool(mods & Gdk.ModifierType.CONTROL_MASK)
        if keyval in RETURN_KEYS:
            self._run()
            return True
        if keyval == Gdk.KEY_Tab and not ctrl:
            self._complete_prefix()
            return True
        if keyval in (Gdk.KEY_Down, Gdk.KEY_KP_Down):
            if self.popover.get_visible() and self.listbox.get_selected_row():
                rows = [r for r in _iter_rows(self.listbox)]
                index = rows.index(self.listbox.get_selected_row())
                if index + 1 < len(rows):
                    self.listbox.select_row(rows[index + 1])
                    return True
            if self._history_index is not None:
                self._history_move(-1)
                return True
            return False
        if keyval in (Gdk.KEY_Up, Gdk.KEY_KP_Up):
            if self.popover.get_visible() and self.listbox.get_selected_row():
                rows = [r for r in _iter_rows(self.listbox)]
                index = rows.index(self.listbox.get_selected_row())
                if index > 0:
                    self.listbox.select_row(rows[index - 1])
                    return True
                self._history_move(-1)
                return True
            self._history_move(1)
            return True
        if keyval == Gdk.KEY_Escape:
            if self.popover.get_visible():
                self.popover.popdown()
                return True
        if ctrl and keyval in (Gdk.KEY_space, Gdk.KEY_p):
            self._on_changed(self.entry)
            return True
        return False

    def _on_row_activated(self, _listbox: Gtk.ListBox, row: Gtk.ListBoxRow) -> None:
        child = row.get_child()
        if isinstance(child, Gtk.Label):
            self._accept(child.get_text())


def _iter_rows(listbox: Gtk.ListBox):
    row = listbox.get_row_at_index(0)
    while row is not None:
        yield row
        row = listbox.get_row_at_index(row.get_index() + 1)


def _common_prefix(values: list[str]) -> str:
    if not values:
        return ""
    prefix = values[0]
    for value in values[1:]:
        while not value.startswith(prefix):
            prefix = prefix[:-1]
            if not prefix:
                return ""
    return prefix

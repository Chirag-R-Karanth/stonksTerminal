from __future__ import annotations

from typing import Any, Callable

from app.ui.gtk import Gtk
from app.ui.views.base import View


class HelpView(View):
    view_name = "help"

    def __init__(self, state: Any, runner: Any, open_panel: Callable[..., None] | None = None):
        super().__init__(state, runner, open_panel)

    def mount(self, payload: dict[str, Any]) -> None:
        topic = payload.get("topic")
        self.set_title(f"HELP {topic}" if topic else "HELP")
        self.clear_content()
        lines = payload.get("lines") or []
        for line in lines:
            label = Gtk.Label(label=line if line else " ", xalign=0)
            label.set_selectable(True)
            self.content.append(label)
        self.set_status([("F1 opens help · TAB completes · ↑ history", "ft-dim")])

    def load(self, force: bool = False) -> None:
        pass

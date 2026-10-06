from __future__ import annotations

import logging
from typing import Any

from app import version
from app.commands.engine import CommandEngine
from app.ui.async_runner import AsyncRunner
from app.ui.console import ConsoleLog
from app.ui.gtk import Gdk, Gio, GLib, Gtk
from app.ui.prompt import Prompt
from app.ui.views.compare import CompareView
from app.ui.views.help import HelpView
from app.ui.views.macro import MacroView
from app.ui.views.markets import MarketsView
from app.ui.views.news import NewsView
from app.ui.views.portfolio import PortfolioView
from app.ui.views.screener import ScreenerView
from app.ui.views.security import SecurityView
from app.ui.views.watchlist import WatchlistView

log = logging.getLogger(__name__)

VIEW_CLASSES = {
    "security": SecurityView,
    "watchlist": WatchlistView,
    "portfolio": PortfolioView,
    "news": NewsView,
    "macro": MacroView,
    "markets": MarketsView,
    "screener": ScreenerView,
    "compare": CompareView,
    "help": HelpView,
}

FKEYS = {
    Gdk.KEY_F1: "HELP",
    Gdk.KEY_F2: "MARKETS",
    Gdk.KEY_F3: "WATCHLIST",
    Gdk.KEY_F4: "PORTFOLIO",
    Gdk.KEY_F5: "NEWS",
    Gdk.KEY_F6: "MACRO",
    Gdk.KEY_F7: "SCREEN",
    Gdk.KEY_F8: "COMPARE",
}


class TerminalWindow(Gtk.ApplicationWindow):
    def __init__(self, application: Gtk.Application, state: Any):
        super().__init__(application=application, title="Financial Terminal")
        self.set_default_size(1440, 900)
        self.state = state
        self.engine = CommandEngine(state)
        self.runner = AsyncRunner(on_busy=self._on_busy)
        self.views: dict[str, Gtk.Widget] = {}
        self.current_payload: dict[str, Any] | None = None

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        root.append(self._build_header())
        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.NONE)
        self.stack.set_vexpand(True)
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_child(self.stack)
        root.append(scrolled)

        bottom = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        bottom.set_margin_start(6)
        bottom.set_margin_end(6)
        bottom.set_margin_top(4)
        bottom.set_margin_bottom(4)
        self.console = ConsoleLog(height=150)
        bottom.append(self.console)
        self.prompt = Prompt(suggest_fn=self.engine.suggest, history_fn=self._history)
        self.prompt.connect("run", self._on_run)
        bottom.append(self.prompt)
        statusbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        self.busy_label = Gtk.Label(label="", xalign=0)
        self.busy_label.add_css_class("ft-warn")
        statusbar.append(self.busy_label)
        self.offline_label = Gtk.Label(label="", xalign=0)
        self.offline_label.add_css_class("ft-err")
        statusbar.append(self.offline_label)
        self.r_label = Gtk.Label(label="", xalign=0)
        self.r_label.add_css_class("ft-dim")
        statusbar.append(self.r_label)
        workspace_name = str(self.state.settings.get("workspace.active", "default"))
        self.workspace_label = Gtk.Label(label=f"ws:{workspace_name}", xalign=0)
        self.workspace_label.add_css_class("ft-dim")
        statusbar.append(self.workspace_label)
        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        statusbar.append(spacer)
        self.clock_label = Gtk.Label(label="", xalign=1)
        self.clock_label.add_css_class("ft-dim")
        statusbar.append(self.clock_label)
        bottom.append(statusbar)
        root.append(bottom)

        self.set_child(root)

        key = Gtk.EventControllerKey()
        key.connect("key-pressed", self._on_key)
        self.add_controller(key)

        self.state.add_listener(self._on_state_event)
        self.state.current_view_fn = lambda: dict(self.current_payload) if self.current_payload else None
        self._tick_clock()
        GLib.timeout_add_seconds(1, self._tick_clock)

        self._banner()
        self._restore_workspace()

    def _build_header(self) -> Gtk.Box:
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        header.add_css_class("ft-header")
        header.set_margin_start(8)
        header.set_margin_end(8)
        header.set_margin_top(4)
        header.set_margin_bottom(4)
        brand = Gtk.Label(label=f"◆ FINANCIAL TERMINAL  {version}", xalign=0)
        brand.add_css_class("ft-accent")
        header.append(brand)
        summary = self.state.status_summary()
        providers = summary.get("providers", {})
        self.provider_label = Gtk.Label(
            label="  ".join(f"{k}:{v}" for k, v in providers.items()),
            xalign=0,
        )
        self.provider_label.add_css_class("ft-dim")
        header.append(self.provider_label)
        self.demo_label = Gtk.Label(label="DEMO DATA", xalign=0)
        self.demo_label.add_css_class("ft-demo")
        self.demo_label.set_visible(bool(summary.get("demo_mode")))
        header.append(self.demo_label)
        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        header.append(spacer)
        return header

    def _banner(self) -> None:
        summary = self.state.status_summary()
        providers = summary.get("providers", {})
        self.console.append(f"FINANCIAL TERMINAL {version} — personal market workstation", "ok")
        self.console.append(
            "providers  " + "  ".join(f"{k}={v}" for k, v in providers.items()), "dim"
        )
        flags = []
        flags.append("R analytics OK" if summary.get("r_available") else "R analytics unavailable (python fallback)")
        if summary.get("demo_mode"):
            flags.append("DEMO MODE — prices are simulated")
        if summary.get("offline"):
            flags.append("OFFLINE")
        self.console.append("  ·  ".join(flags), "warn" if (summary.get("demo_mode") or summary.get("offline")) else "info")
        self.console.append("type HELP for commands · symbol + action for detail · F1..F8 views", "dim")
        self.r_label.set_text("R:ok" if summary.get("r_available") else "R:n/a")

    def _restore_workspace(self) -> None:
        try:
            layouts = self.state.settings.get("workspace.layouts", {}) or {}
            active = str(self.state.settings.get("workspace.active", "default"))
            layout = layouts.get(active) or {}
            if isinstance(layout, dict) and layout.get("view"):
                self.open_panel(dict(layout))
        except Exception as exc:
            log.warning("workspace restore failed: %s", exc)

    def _history(self) -> list[str]:
        try:
            return list(self.state.history.recent(100))
        except Exception:
            return []

    def _on_run(self, _prompt: Prompt, text: str) -> None:
        self.execute(text)

    def execute(self, text: str) -> None:
        stripped = text.strip()
        if not stripped:
            return
        self.console.append(f"FT> {stripped}", "cmd")
        outcome = self.engine.execute(stripped)
        kind = outcome.kind
        if kind == "panel" and outcome.panel:
            self.open_panel(outcome.panel)
            return
        if kind == "clear":
            self.console.clear()
            return
        if kind == "refresh":
            child = self.stack.get_visible_child()
            refresh = getattr(child, "refresh", None)
            if callable(refresh):
                refresh(force=True)
            return
        level = outcome.level if outcome.level in ("info", "warn", "err", "ok", "dim") else "info"
        if not outcome.ok:
            level = "err"
        if outcome.text:
            self.console.append(outcome.text, level)
        if outcome.suggestions:
            self.console.append("did you mean: " + " | ".join(outcome.suggestions[:8]), "dim")

    def open_panel(self, payload: dict[str, Any]) -> None:
        name = str(payload.get("view", "")).lower()
        view_cls = VIEW_CLASSES.get(name)
        if view_cls is None:
            self.console.append(f"unknown view {name!r}", "err")
            return
        view = self.views.get(name)
        if view is None:
            view = view_cls(self.state, self.runner, open_panel=self.open_panel)
            self.views[name] = view
            self.stack.add_named(view, name)
        self.stack.set_visible_child(view)
        self.current_payload = {"view": name, **{k: v for k, v in payload.items() if k != "view"}}
        try:
            view.mount(payload)
        except Exception as exc:
            log.exception("view mount failed: %s", name)
            self.console.append(f"{name} view failed: {exc}", "err")
        self.prompt.focus()

    def _on_key(self, _ctrl: Gtk.EventControllerKey, keyval: int, _code: int, mods: int) -> bool:
        control = bool(mods & Gdk.ModifierType.CONTROL_MASK)
        if keyval in FKEYS and not control:
            command = FKEYS[keyval]
            if keyval == Gdk.KEY_F8:
                command = self._compare_command()
            self.execute(command)
            return True
        if control and keyval in (Gdk.KEY_r, Gdk.KEY_R):
            child = self.stack.get_visible_child()
            refresh = getattr(child, "refresh", None)
            if callable(refresh):
                refresh(force=True)
                self.console.append("refresh", "dim")
            return True
        if control and keyval in (Gdk.KEY_l, Gdk.KEY_L):
            self.console.clear()
            return True
        return False

    def _compare_command(self) -> str:
        try:
            symbols = [str(s) for s in self.state.watchlist_repo.all_symbols()[:3]]
        except Exception:
            symbols = []
        if len(symbols) >= 2:
            return "COMPARE " + " ".join(symbols)
        return "COMPARE"

    def _on_busy(self, busy: bool) -> None:
        self.busy_label.set_text("⟳ BUSY" if busy else "")

    def _on_state_event(self, event: str, payload: dict[str, Any]) -> None:
        if event == "offline":
            self.offline_label.set_text("OFFLINE" if payload.get("offline") else "")
        elif event == "workspace":
            self.workspace_label.set_text(f"ws:{payload.get('name', '')}")
            layout = payload.get("layout") or {}
            if isinstance(layout, dict) and layout.get("view"):
                self.open_panel(dict(layout))

    def _tick_clock(self) -> bool:
        import time

        self.clock_label.set_text(time.strftime("%Y-%m-%d %H:%M:%S"))
        return True


class TerminalApp(Gtk.Application):
    def __init__(self, state: Any):
        super().__init__(
            application_id="org.bloombergridge.financialterminal",
            flags=Gio.ApplicationFlags.FLAGS_NONE,
        )
        self.state = state
        self.window: TerminalWindow | None = None

    def do_activate(self) -> None:
        Gtk.Application.do_activate(self)
        if self.window is None:
            self.window = TerminalWindow(self, self.state)
        self.window.present()

    def do_shutdown(self) -> None:
        if self.window is not None:
            try:
                self.window.runner.stop()
            except Exception as exc:
                log.warning("runner stop failed: %s", exc)
        try:
            self.state.close()
        except Exception as exc:
            log.warning("state close failed: %s", exc)
        Gtk.Application.do_shutdown(self)

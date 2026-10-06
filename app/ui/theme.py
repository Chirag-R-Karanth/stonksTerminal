from __future__ import annotations

from app.ui.gtk import Gdk, Gtk

BG = "#0b0e14"
PANEL = "#12161f"
PANEL_ALT = "#0e121a"
BORDER = "#242b38"
FG = "#d7dce5"
DIM = "#7b8494"
AMBER = "#ffb000"
GREEN = "#3fd18b"
RED = "#ff5c66"
BLUE = "#58a6ff"
CYAN = "#54d1d5"
MAGENTA = "#c792ea"
YELLOW = "#ffd166"

CSS = f"""
window, .ft-root {{
  background-color: {BG};
  color: {FG};
  font-family: "DejaVu Sans Mono", "Monospace", monospace;
  font-size: 11px;
}}
.ft-title {{
  color: {AMBER};
  font-weight: bold;
  font-size: 13px;
}}
.ft-header {{
  background-color: {PANEL};
  border-bottom: 1px solid {BORDER};
  padding: 4px 8px;
}}
.ft-panel {{
  background-color: {PANEL};
  border: 1px solid {BORDER};
  padding: 6px;
}}
.ft-section {{
  color: {AMBER};
  font-weight: bold;
  padding-top: 4px;
}}
.ft-status {{
  background-color: {PANEL_ALT};
  border-top: 1px solid {BORDER};
  padding: 3px 8px;
  color: {DIM};
}}
.ft-dim {{ color: {DIM}; }}
.ft-up {{ color: {GREEN}; }}
.ft-down {{ color: {RED}; }}
.ft-warn {{ color: {YELLOW}; }}
.ft-err {{ color: {RED}; }}
.ft-accent {{ color: {AMBER}; }}
.ft-link {{ color: {BLUE}; text-decoration: underline; }}
.ft-table-header {{
  background-color: {PANEL_ALT};
  color: {AMBER};
  font-weight: bold;
  border-bottom: 1px solid {BORDER};
  padding: 3px 6px;
}}
.ft-row {{
  padding: 2px 6px;
  border-bottom: 1px solid #1a2029;
}}
.ft-row:hover {{
  background-color: #1b2330;
}}
.ft-row-alt {{
  background-color: {PANEL_ALT};
}}
.ft-prompt-entry {{
  background-color: {PANEL};
  color: {AMBER};
  border: 1px solid {BORDER};
  caret-color: {AMBER};
  padding: 4px 6px;
}}
.ft-prompt-entry:focus {{
  border-color: {AMBER};
}}
.ft-log {{
  background-color: {BG};
  color: {FG};
  padding: 4px;
}}
.ft-completion {{
  background-color: {PANEL};
  border: 1px solid {AMBER};
  color: {FG};
}}
.ft-completion row {{
  padding: 2px 8px;
}}
.ft-completion row:selected {{
  background-color: #2a3140;
  color: {AMBER};
}}
.ft-button {{
  background-color: {PANEL_ALT};
  color: {FG};
  border: 1px solid {BORDER};
  padding: 2px 8px;
}}
.ft-button:hover {{
  border-color: {AMBER};
  color: {AMBER};
}}
.ft-button:checked {{
  background-color: #2a3140;
  color: {AMBER};
  border-color: {AMBER};
}}
.ft-demo {{
  background-color: #5a3000;
  color: {YELLOW};
  font-weight: bold;
  padding: 2px 8px;
}}
.ft-offline {{
  background-color: #4a1015;
  color: {RED};
  font-weight: bold;
  padding: 2px 8px;
}}
.ft-scroll {{
  background-color: {BG};
}}
ft-numeric {{
  font-feature-settings: "tnum";
}}
"""

_provider: Gtk.CssProvider | None = None


def load() -> Gtk.CssProvider:
    global _provider
    if _provider is None:
        _provider = Gtk.CssProvider()
        _provider.load_from_data(CSS.encode("utf-8"))
        display = Gdk.Display.get_default()
        if display is not None:
            Gtk.StyleContext.add_provider_for_display(
                display,
                _provider,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
            )
    return _provider


def apply(widget: Gtk.Widget, css_class: str) -> Gtk.Widget:
    widget.add_css_class(css_class)
    return widget

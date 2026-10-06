import subprocess
import sys

sys.path.insert(0, "/home/neo_phantom_byte/Documents/bloombergTerminal")

from app.main import _make_state, build_parser

args = build_parser().parse_args(["--demo"])
state = _make_state(args)
state.db.execute("DELETE FROM transactions")
state.db.execute("DELETE FROM watchlist_items")

from app.ui import theme
from app.ui.gtk import Gdk, GLib
from app.ui.window import TerminalApp

theme.load()
app = TerminalApp(state)
shot = {"n": 0}


def screenshot(tag):
    shot["n"] += 1
    monitors = Gdk.Display.get_default().get_monitors()
    geom = monitors[0].get_geometry() if monitors.get_n_items() else None
    size = f"{geom.width}x{geom.height}" if geom else "1600x900"
    path = f"/tmp/opencode/shot_{shot['n']:02d}_{tag}.png"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "x11grab", "-video_size", size, "-i", ":0.0",
         "-update", "1", "-frames:v", "1", path],
        timeout=15, capture_output=True,
    )
    print("screenshot:", path)


cmds = [
    ("WL ADD AAPL", None),
    ("WL ADD MSFT", None),
    ("WL", None),
    ("PORTFOLIO ADD AAPL 10 250", None),
    ("PORTFOLIO ADD MSFT 5 420", None),
    ("PORTFOLIO BENCHMARK ^GSPC", None),
    ("PORTFOLIO", "holdings"),
    ("PORTFOLIO RISK", "risk"),
    ("PORTFOLIO PERFORMANCE", "perf"),
    ("PORTFOLIO HISTORY", "history"),
    ("AAPL CHART", "chart"),
    ("AAPL VAL", "val"),
    ("AAPL FIN", "fin"),
    ("AAPL RISK", "secrisk"),
    ("SCREEN PE<20 MARKETCAP>1e9", "screen"),
    ("MACRO US_DGS10", "macro10"),
    ("MACRO", "macroov"),
    ("MARKETS", "markets"),
    ("COMPARE AAPL MSFT GOOG", "compare"),
    ("NEWS", "news"),
    ("HELP SCREEN", "help"),
    ("STATUS", None),
    ("TYPOHERE", None),
]


def start():
    box = {"i": 0}

    def tick():
        i = box["i"]
        if i >= len(cmds):
            dump()
            screenshot("final")
            app.quit()
            return False
        text, tag = cmds[i]
        app.window.execute(text)
        box["i"] += 1
        if tag:
            GLib.timeout_add(1500, _shot, tag)
        return True

    GLib.timeout_add(700, tick_first, tick)
    return False


def tick_first(tick):
    GLib.timeout_add(2200, tick)
    return False


def _shot(tag):
    screenshot(tag)
    return False


def dump():
    buf = app.window.console.view.get_buffer()
    s, e = buf.get_bounds()
    print("=== CONSOLE DUMP ===")
    print(buf.get_text(s, e, True))
    print("=== END ===")
    for name, view in app.window.views.items():
        statuses = []
        child = view.status_box.get_first_child()
        while child is not None:
            statuses.append(child.get_text() if hasattr(child, "get_text") else "?")
            child = child.get_next_sibling()
        print(f"view {name}: title={view.title_text!r} children={view.content.get_first_child() is not None} status={' | '.join(statuses)}")
    wl = app.window.views.get("watchlist")
    if wl is not None:
        print("watchlist rows attr:", getattr(wl, "rows", "n/a"))
    pf = app.window.views.get("portfolio")
    if pf is not None:
        print("portfolio rows:", len(getattr(pf, "rows", []) or []))


GLib.timeout_add(600, start)
rc = app.run([sys.argv[0]])
print("run rc:", rc)

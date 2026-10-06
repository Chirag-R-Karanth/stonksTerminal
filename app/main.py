from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from app import version
from app.config import Config
from app.logging_setup import setup_logging


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="terminal",
        description="personal Bloomberg-style financial terminal",
    )
    parser.add_argument("--config", type=Path, default=None, help="path to user config.toml")
    parser.add_argument("--demo", action="store_true", help="force demo mode (simulated data, always labeled)")
    parser.add_argument("--offline", action="store_true", help="start in offline mode (cache only)")
    parser.add_argument("--check", action="store_true", help="run environment checks and exit")
    parser.add_argument("--version", action="version", version=f"%(prog)s {version}")
    return parser


def _make_state(args: argparse.Namespace) -> Any:
    from app.state.app_state import AppState

    config = Config.load(user_path=args.config)
    if args.demo:
        config.set("data.demo_mode", True)
    setup_logging(str(config.get("terminal.log_level", "INFO")))
    state = AppState.create(config)
    if args.offline:
        state.set_offline(True)
    return state


def run_check(state: Any) -> int:
    ok = True
    summary = state.status_summary()
    print(f"financial-terminal {version}")
    print(f"config       : {getattr(state.config, '_user_path', '?')}")
    print(f"database     : {summary['db_path']}")
    print(f"data dir     : {summary['data_dir']}")
    for role, name in summary["providers"].items():
        print(f"provider.{role:<12}: {name}")
    print(f"r analytics  : {'available' if summary['r_available'] else 'UNAVAILABLE (python fallback)'}")
    print(f"demo mode    : {summary['demo_mode']}")
    print(f"offline      : {summary['offline']}")
    print(f"universe     : {summary['universe_size']} symbols")
    print(f"watchlists   : {', '.join(summary['watchlists']) or '(none)'}")
    print(f"quote ttl    : {summary['quote_ttl']}s   news ttl: {summary['news_ttl']}s")
    try:
        print(f"migrations   : user_version={state.db.user_version()} files={len(state.db.migration_files())}")
        if not state.db.verify():
            print("integrity    : FAILED")
            ok = False
    except Exception as exc:
        print(f"migrations   : FAILED ({exc})")
        ok = False
    state.close()
    return 0 if ok else 1


def run_gui(state: Any) -> int:
    from app.ui import theme
    from app.ui.gtk import Gtk
    from app.ui.window import TerminalApp

    theme.load()
    app = TerminalApp(state)
    try:
        return int(app.run(sys.argv))
    except Exception as exc:
        print(f"failed to start GUI: {exc}", file=sys.stderr)
        state.close()
        return 1


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        state = _make_state(args)
    except Exception as exc:
        print(f"startup failed: {exc}", file=sys.stderr)
        return 1
    if args.check:
        return run_check(state)
    return run_gui(state)


if __name__ == "__main__":
    sys.exit(main())

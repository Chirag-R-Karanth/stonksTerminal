from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from app.commands.outcome import CommandOutcome, error
from app.commands.parser import ParseError, parse
from app.commands.registry import SYMBOL_ACTIONS, command_names, resolve_verb, spec_for

if TYPE_CHECKING:
    from app.state.app_state import AppState

log = logging.getLogger(__name__)

MAX_SUGGESTIONS = 12
SYMBOL_PREFIX_RE = re.compile(r"^[A-Za-z0-9^][A-Za-z0-9.\-^=]*$")
FILTER_HINT = re.compile(r"[<>=!]")


class CommandEngine:
    def __init__(self, state: "AppState"):
        self.state = state

    def execute(self, text: str) -> CommandOutcome:
        from app.commands import handlers

        stripped = text.strip()
        if not stripped:
            return CommandOutcome(ok=True, kind="message", text="")
        try:
            command = parse(stripped)
        except ParseError as exc:
            return error(str(exc), suggestions=exc.suggestions or self.suggest(stripped))
        try:
            self.state.history.add(stripped)
        except Exception as exc:
            log.warning("history add failed: %s", exc)
        try:
            if command.kind == "symbol":
                return handlers.handle_symbol(self.state, command)
            return handlers.dispatch(self.state, command)
        except Exception as exc:
            log.exception("command failed: %s", stripped)
            return error(f"{type(exc).__name__}: {exc}")

    def suggest(self, text: str) -> list[str]:
        head, sep, tail = text.rpartition(" ")
        prefix = tail.upper()
        if not sep:
            return _dedupe(
                name + " " for name in command_names() if name.startswith(prefix)
            )[:MAX_SUGGESTIONS]
        first = head.split()[0].upper()
        candidates: list[str] = []
        if resolve_verb(first) in {spec.name for spec in _all_specs()}:
            spec = spec_for(resolve_verb(first))
            if spec and not FILTER_HINT.search(tail):
                words = re.split(r"[\[\]|]", spec.usage)
                for word in words:
                    token = word.strip().split(" ")[0].strip("...")
                    if token and token.upper().startswith(prefix) and token.upper() != first:
                        candidates.append(token)
        elif SYMBOL_PREFIX_RE.match(first) and not FILTER_HINT.search(tail):
            for action in SYMBOL_ACTIONS:
                if action.startswith(prefix):
                    candidates.append(action)
            for period in ("1Y", "6M", "3M", "1M", "5D", "INTRA"):
                if period.startswith(prefix):
                    candidates.append(period)
            candidates.extend(_local_symbols(self, prefix))
        elif resolve_verb(first) in ("WATCHLIST", "PORTFOLIO") and not FILTER_HINT.search(tail):
            for token in ("ADD", "REMOVE", "CREATE", "DELETE", "USE", "RISK", "HISTORY"):
                if token.startswith(prefix):
                    candidates.append(token)
        return _dedupe(
            [f"{head} {c}".strip() if head else c for c in candidates]
        )[:MAX_SUGGESTIONS]


def _all_specs() -> list:
    from app.commands.registry import COMMANDS

    return list(COMMANDS.values())


def _local_symbols(engine: CommandEngine, prefix: str) -> list[str]:
    out: list[str] = []
    try:
        for info in engine.state.market.search_local(prefix, limit=8):
            if info.symbol.upper().startswith(prefix):
                out.append(info.symbol)
    except Exception as exc:
        log.warning("local symbol suggest failed: %s", exc)
    try:
        for symbol in engine.state.watchlist_repo.all_symbols():
            if symbol.upper().startswith(prefix):
                out.append(symbol)
    except Exception as exc:
        log.warning("watchlist suggest failed: %s", exc)
    return out


def _dedupe(values: list[str]) -> list[str]:
    seen: dict[str, None] = {}
    for value in values:
        if value and value not in seen:
            seen[value] = None
    return list(seen)

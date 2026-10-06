from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.commands.registry import SYMBOL_ACTIONS, is_command, resolve_verb
from app.commands.tokenizer import Token, TokenError, tokenize

SYMBOL_RE = re.compile(r"^[A-Za-z0-9^][A-Za-z0-9.\-^=]*$")


class ParseError(ValueError):
    def __init__(self, message: str, suggestions: list[str] | None = None):
        super().__init__(message)
        self.suggestions = suggestions or []


@dataclass
class Filter:
    field: str
    op: str
    value: float
    raw: str

    def text(self) -> str:
        return self.raw


@dataclass
class Command:
    kind: str
    raw: str
    verb: str = ""
    symbol: str = ""
    action: str = ""
    args: list[str] = field(default_factory=list)
    filters: list[Filter] = field(default_factory=list)

    @property
    def text(self) -> str:
        if self.kind == "symbol":
            parts = [self.symbol, self.action, *self.args]
        else:
            parts = [self.verb, *self.args]
        parts.extend(f.text() for f in self.filters)
        return " ".join(parts)


def _number(value: str) -> float:
    if value.endswith("%"):
        return float(value[:-1]) / 100.0
    return float(value)


def _split(tokens: list[Token]) -> tuple[list[Filter], list[str]]:
    filters: list[Filter] = []
    words: list[str] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if (
            token.kind == "WORD"
            and index + 2 < len(tokens)
            and tokens[index + 1].kind == "OP"
            and tokens[index + 2].kind == "NUMBER"
        ):
            filters.append(
                Filter(
                    field=token.value,
                    op=tokens[index + 1].value,
                    value=_number(tokens[index + 2].value),
                    raw=f"{token.value}{tokens[index + 1].value}{tokens[index + 2].value}",
                )
            )
            index += 3
            continue
        if token.kind == "WORD":
            words.append(token.value)
        elif token.kind == "STRING":
            words.append(token.value)
        elif token.kind == "NUMBER":
            words.append(token.value)
        index += 1
    return filters, words


def parse(text: str) -> Command:
    raw = text.strip()
    if not raw:
        raise ParseError("empty command")
    try:
        tokens = tokenize(raw)
    except TokenError as exc:
        raise ParseError(str(exc)) from exc
    if not tokens:
        raise ParseError("empty command")
    filters, words = _split(tokens)
    if not words:
        raise ParseError("missing command or symbol")
    first = words[0]
    if is_command(first):
        verb = resolve_verb(first)
        return Command(kind="command", raw=raw, verb=verb, args=words[1:], filters=filters)
    candidate = first.upper()
    if not SYMBOL_RE.match(candidate):
        raise ParseError(
            f"unknown command or invalid symbol: {first!r}",
            suggestions=[c.name for c in _suggest_commands(first)],
        )
    action = ""
    args = words[1:]
    if args and args[0].upper() in SYMBOL_ACTIONS:
        action = args[0].upper()
        args = args[1:]
    return Command(
        kind="symbol", raw=raw, symbol=candidate, action=action, args=args, filters=filters
    )


def _suggest_commands(prefix: str) -> list:
    from app.commands.registry import COMMANDS

    lowered = prefix.lower()
    return [spec for spec in COMMANDS.values() if spec.name.lower().startswith(lowered)]

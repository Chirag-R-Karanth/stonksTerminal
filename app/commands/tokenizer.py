from __future__ import annotations

import re
from dataclasses import dataclass


class TokenError(ValueError):
    pass


@dataclass(frozen=True)
class Token:
    kind: str
    value: str


TOKEN_RE = re.compile(
    r"""
      (?P<ws>\s+)
    | (?P<str>"[^"]*"|'[^']*')
    | (?P<date>\d{4}-\d{1,2}-\d{1,2})
    | (?P<op><=|>=|==|!=|<|>|=)
    | (?P<num>-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?%?(?![A-Za-z]))
    | (?P<word>[^\s<>=!]+)
    """,
    re.VERBOSE,
)


def tokenize(text: str) -> list[Token]:
    tokens: list[Token] = []
    pos = 0
    length = len(text)
    while pos < length:
        match = TOKEN_RE.match(text, pos)
        if match is None:
            raise TokenError(f"unexpected character {text[pos]!r}")
        pos = match.end()
        kind = match.lastgroup
        value = match.group()
        if kind == "ws":
            continue
        if kind == "str":
            tokens.append(Token("STRING", value[1:-1]))
        elif kind == "op":
            tokens.append(Token("OP", "==") if value == "=" else Token("OP", value))
        elif kind in ("num", "date"):
            tokens.append(Token("WORD" if kind == "date" else "NUMBER", value))
        else:
            tokens.append(Token("WORD", value))
    return tokens

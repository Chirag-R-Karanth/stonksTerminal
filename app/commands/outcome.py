from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class CommandOutcome:
    ok: bool
    kind: str
    text: str = ""
    level: str = "info"
    panel: dict[str, Any] | None = None
    suggestions: list[str] = field(default_factory=list)


def message(text: str, level: str = "info") -> CommandOutcome:
    return CommandOutcome(ok=True, kind="message", text=text, level=level)


def error(text: str, suggestions: list[str] | None = None) -> CommandOutcome:
    return CommandOutcome(
        ok=False, kind="error", text=text, level="error", suggestions=suggestions or []
    )


def panel(view: str, **payload: Any) -> CommandOutcome:
    data = {"view": view, **payload}
    return CommandOutcome(ok=True, kind="panel", panel=data)

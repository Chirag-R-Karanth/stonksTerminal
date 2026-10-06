from __future__ import annotations

import json
import os
import re
import tomllib
from pathlib import Path
from typing import Any

from app import paths


class Config:
    def __init__(self, defaults: dict[str, Any], user: dict[str, Any], user_path: Path):
        self._defaults = defaults
        self._user = user
        self._user_path = user_path

    @classmethod
    def load(cls, default_path: Path | None = None, user_path: Path | None = None) -> "Config":
        default_path = default_path or paths.repo_root() / "config" / "default.toml"
        user_path = user_path or paths.user_config_path()
        with open(default_path, "rb") as fh:
            defaults = tomllib.load(fh)
        user: dict[str, Any] = {}
        if user_path.exists():
            try:
                with open(user_path, "rb") as fh:
                    user = tomllib.load(fh)
            except (tomllib.TOMLDecodeError, OSError):
                backup = user_path.with_suffix(".toml.corrupt")
                try:
                    user_path.replace(backup)
                except OSError:
                    pass
                user = {}
        return cls(defaults, user, user_path)

    def get(self, dotted: str, default: Any = None) -> Any:
        node: Any = self._user
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                break
            node = node[part]
        else:
            return node
        node = self._defaults
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def section(self, dotted: str) -> dict[str, Any]:
        merged: dict[str, Any] = {}
        for source in (self._defaults, self._user):
            node = source
            ok = True
            for part in dotted.split("."):
                if not isinstance(node, dict) or part not in node:
                    ok = False
                    break
                node = node[part]
            if ok and isinstance(node, dict):
                merged.update(node)
        return merged

    def set(self, dotted: str, value: Any) -> None:
        parts = dotted.split(".")
        node = self._user
        for part in parts[:-1]:
            child = node.get(part)
            if not isinstance(child, dict):
                child = {}
                node[part] = child
            node = child
        node[parts[-1]] = value
        self._save()

    def delete(self, dotted: str) -> None:
        parts = dotted.split(".")
        node = self._user
        for part in parts[:-1]:
            child = node.get(part)
            if not isinstance(child, dict):
                return
            node = child
        node.pop(parts[-1], None)
        self._save()

    def all(self) -> dict[str, Any]:
        merged: dict[str, Any] = {}

        def walk(node: dict[str, Any], prefix: str) -> None:
            for key, value in node.items():
                dotted_key = f"{prefix}{key}"
                if isinstance(value, dict):
                    walk(value, f"{dotted_key}.")
                else:
                    merged[dotted_key] = value

        walk(self._defaults, "")
        walk(self._user, "")
        return merged

    def secret(self, key: str, env: str | None = None) -> str | None:
        if env:
            value = os.environ.get(env, "").strip()
            if value:
                return value
        value = self.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        return None

    def _save(self) -> None:
        paths.config_dir().mkdir(parents=True, exist_ok=True)
        text = _dump_toml(self._user)
        tmp = self._user_path.with_suffix(".toml.tmp")
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, self._user_path)


_KEY_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def _toml_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, str):
        return json.dumps(value)
    if isinstance(value, list):
        return "[" + ", ".join(_toml_scalar(v) for v in value) + "]"
    raise TypeError(f"unsupported toml value: {type(value)!r}")


def _dump_toml(data: dict[str, Any], prefix: str = "") -> str:
    lines: list[str] = []
    scalars = [(k, v) for k, v in data.items() if not isinstance(v, dict)]
    tables = [(k, v) for k, v in data.items() if isinstance(v, dict)]
    for key, value in scalars:
        lines.append(f"{key} = {_toml_scalar(value)}")
    for key, value in tables:
        if not _KEY_RE.match(key):
            raise TypeError(f"invalid table key: {key!r}")
        header = f"{prefix}{key}"
        if lines:
            lines.append("")
        lines.append(f"[{header}]")
        lines.append(_dump_toml(value, prefix=f"{header}."))
    return "\n".join(lines) + "\n"

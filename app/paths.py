from __future__ import annotations

import os
from pathlib import Path

APP_DIR = "financial-terminal"


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _xdg(env: str, fallback: str) -> Path:
    value = os.environ.get(env)
    base = Path(value) if value else Path.home() / fallback
    return base / APP_DIR


def config_dir() -> Path:
    return _xdg("XDG_CONFIG_HOME", ".config")


def data_dir() -> Path:
    return _xdg("XDG_DATA_HOME", ".local/share")


def state_dir() -> Path:
    return _xdg("XDG_STATE_HOME", ".local/state")


def log_dir() -> Path:
    return state_dir() / "logs"


def backup_dir() -> Path:
    return state_dir() / "backups"


def db_path() -> Path:
    return data_dir() / "terminal.db"


def duckdb_path() -> Path:
    return data_dir() / "analytics.duckdb"


def parquet_dir() -> Path:
    return data_dir() / "parquet"


def user_config_path() -> Path:
    return config_dir() / "config.toml"


def ensure_dirs() -> None:
    for path in (config_dir(), data_dir(), state_dir(), log_dir(), backup_dir(), parquet_dir()):
        path.mkdir(parents=True, exist_ok=True)

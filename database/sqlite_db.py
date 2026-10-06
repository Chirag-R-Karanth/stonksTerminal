from __future__ import annotations

import shutil
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from app import paths

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
KEEP_BACKUPS = 10


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


class MigrationError(RuntimeError):
    pass


class Database:
    def __init__(self, path: Path | None = None):
        self.path = path or paths.db_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._migration_lock = threading.Lock()

    def connection(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(str(self.path), timeout=10.0)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA busy_timeout = 10000")
            self._local.conn = conn
        return conn

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        conn = self.connection()
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    def execute(self, sql: str, params: tuple | dict = ()) -> sqlite3.Cursor:
        conn = self.connection()
        cur = conn.execute(sql, params)
        conn.commit()
        return cur

    def query(self, sql: str, params: tuple | dict = ()) -> list[sqlite3.Row]:
        return list(self.connection().execute(sql, params).fetchall())

    def query_one(self, sql: str, params: tuple | dict = ()) -> sqlite3.Row | None:
        return self.connection().execute(sql, params).fetchone()

    def close(self) -> None:
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None

    def user_version(self) -> int:
        return int(self.connection().execute("PRAGMA user_version").fetchone()[0])

    def migration_files(self) -> list[tuple[int, Path]]:
        files: list[tuple[int, Path]] = []
        for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            prefix = path.name.split("_", 1)[0]
            if prefix.isdigit():
                files.append((int(prefix), path))
        return files

    def migrate(self) -> list[int]:
        with self._migration_lock:
            return self._migrate()

    def _migrate(self) -> list[int]:
        applied: list[int] = []
        current = self.user_version()
        pending = [(v, p) for v, p in self.migration_files() if v > current]
        if not pending:
            return applied

        backup_path = self.backup(prefix=f"pre-migration-v{current}")
        for version, path in pending:
            sql = path.read_text(encoding="utf-8")
            conn = self.connection()
            try:
                conn.executescript("BEGIN;\n" + sql + f"\nPRAGMA user_version = {version};\nCOMMIT;")
            except Exception as exc:
                try:
                    conn.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
                self._restore(backup_path)
                raise MigrationError(
                    f"migration {path.name} failed: {exc}; restored backup {backup_path}"
                ) from exc
            if not self.verify():
                self._restore(backup_path)
                raise MigrationError(
                    f"integrity check failed after {path.name}; restored backup {backup_path}"
                )
            applied.append(version)
        return applied

    def verify(self) -> bool:
        row = self.connection().execute("PRAGMA quick_check").fetchone()
        return bool(row) and str(row[0]).lower() == "ok"

    def backup(self, prefix: str = "backup") -> Path:
        paths.backup_dir().mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        dest = paths.backup_dir() / f"{self.path.stem}-{prefix}-{stamp}.db"
        conn = self.connection()
        try:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except sqlite3.Error:
            pass
        target = sqlite3.connect(str(dest))
        try:
            conn.backup(target)
        finally:
            target.close()
        self._prune_backups()
        return dest

    def _restore(self, backup_path: Path) -> None:
        self.close()
        for suffix in ("", "-wal", "-shm"):
            candidate = Path(str(self.path) + suffix)
            if candidate.exists():
                candidate.unlink()
        shutil.copy2(backup_path, self.path)

    def _prune_backups(self) -> None:
        backups = sorted(paths.backup_dir().glob(f"{self.path.stem}-*.db"))
        for stale in backups[:-KEEP_BACKUPS]:
            try:
                stale.unlink()
            except OSError:
                pass


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None

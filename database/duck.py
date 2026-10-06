from __future__ import annotations

import re
import threading
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

PRICE_COLUMNS = ["ts", "open", "high", "low", "close", "volume"]
_SAFE_RE = re.compile(r"[^A-Za-z0-9_.=-]+")


def _safe_name(symbol: str) -> str:
    return _SAFE_RE.sub("_", symbol)


class AnalyticStore:
    def __init__(self, parquet_dir: Path, duck_path: Path):
        self.parquet_dir = parquet_dir
        self.duck_path = duck_path
        self.parquet_dir.mkdir(parents=True, exist_ok=True)
        self.duck_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn: duckdb.DuckDBPyConnection | None = None

    @property
    def conn(self) -> duckdb.DuckDBPyConnection:
        with self._lock:
            if self._conn is None:
                self._conn = duckdb.connect(str(self.duck_path))
            return self._conn

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    def price_file(self, symbol: str) -> Path:
        return self.parquet_dir / f"{_safe_name(symbol)}.parquet"

    def write_prices(self, symbol: str, frame: pd.DataFrame, interval: str) -> None:
        if frame.empty:
            return
        df = frame.copy()
        df["symbol"] = symbol
        df["interval"] = interval
        for col in PRICE_COLUMNS:
            if col not in df.columns:
                raise ValueError(f"price frame missing column {col}")
        df = df[["symbol", "interval", *PRICE_COLUMNS]]
        path = self.price_file(symbol)
        if path.exists():
            existing = pd.read_parquet(path)
            df = pd.concat([existing, df], ignore_index=True)
            df = df.drop_duplicates(subset=["interval", "ts"], keep="last")
        df = df.sort_values(["interval", "ts"])
        tmp = path.with_suffix(".parquet.tmp")
        df.to_parquet(tmp, index=False)
        tmp.replace(path)

    def read_prices(
        self,
        symbol: str,
        interval: str | None = None,
        start: Any = None,
        end: Any = None,
    ) -> pd.DataFrame:
        path = self.price_file(symbol)
        if not path.exists():
            return pd.DataFrame(columns=["symbol", "interval", *PRICE_COLUMNS])
        df = pd.read_parquet(path)
        if interval:
            df = df[df["interval"] == interval]
        if start is not None:
            df = df[df["ts"] >= start]
        if end is not None:
            df = df[df["ts"] <= end]
        return df.reset_index(drop=True)

    def price_matrix(self, symbols: list[str], start: Any = None) -> pd.DataFrame:
        if not symbols:
            return pd.DataFrame()
        files = [str(self.price_file(s)) for s in symbols if self.price_file(s).exists()]
        if not files:
            return pd.DataFrame()
        glob = files[0] if len(files) == 1 else "{" + ",".join(files) + "}"
        sql = (
            f"SELECT ts, filename, close, interval FROM read_parquet('{glob}', filename=true) "
            "WHERE interval = '1d'"
        )
        frame = self.conn.execute(sql).fetchdf()
        if frame.empty:
            return frame
        frame["symbol"] = frame["filename"].map(
            lambda p: Path(p).stem if isinstance(p, str) else str(p)
        )
        if start is not None:
            frame = frame[frame["ts"] >= start]
        pivot = frame.pivot_table(index="ts", columns="symbol", values="close", aggfunc="last")
        return pivot.sort_index()

    def register(self, name: str, frame: pd.DataFrame) -> None:
        self.conn.register(name, frame)

    def query(self, sql: str) -> pd.DataFrame:
        return self.conn.execute(sql).fetchdf()

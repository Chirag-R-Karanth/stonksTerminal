from __future__ import annotations

import logging
import threading
from typing import Any

from app.config import Config
from data.cache import DataCache
from data.models import STATUS_ERROR, DataResult, MacroObservation, MacroSeries
from data.providers.base import MacroDataProvider

log = logging.getLogger(__name__)

YIELD_CURVE_KEYS: dict[int, str] = {
    2: "US_DGS2",
    5: "US_DGS5",
    10: "US_DGS10",
    30: "US_DGS30",
}


class MacroService:
    def __init__(self, provider: MacroDataProvider, cache: DataCache, config: Config):
        self.provider = provider
        self.cache = cache
        self.config = config
        self._lock = threading.Lock()

    @property
    def name(self) -> str:
        return self.provider.name

    def catalog(self) -> list[dict[str, str]]:
        out = []
        for key, entry in sorted((self.config.section("macro_series") or {}).items()):
            if not isinstance(entry, dict):
                continue
            out.append(
                {
                    "key": key,
                    "series": str(entry.get("series", key)),
                    "title": str(entry.get("title", key)),
                    "units": str(entry.get("units", "")),
                }
            )
        return out

    def _entry(self, key: str) -> dict[str, Any]:
        catalog = {c["key"]: c for c in self.catalog()}
        wanted = key.upper()
        if wanted in catalog:
            return catalog[wanted]
        for entry in catalog.values():
            if entry["series"].upper() == wanted:
                return entry
        return {"key": wanted, "series": wanted, "title": wanted, "units": ""}

    def series(self, key: str, force: bool = False) -> DataResult[MacroSeries]:
        entry = self._entry(key)
        series_id = entry["series"]
        with self._lock:
            result = self.cache.get_macro(
                series_id,
                self.provider.name,
                lambda: self.provider.series(series_id),
                force=force,
            )
        if result.data is not None:
            data = result.data
            if entry["title"] and data.title in ("", series_id):
                data.title = entry["title"]
            if entry["units"] and not data.units:
                data.units = entry["units"]
        return result

    def overview(self, force: bool = False) -> dict[str, DataResult[MacroSeries]]:
        out: dict[str, DataResult[MacroSeries]] = {}
        for entry in self.catalog():
            out[entry["key"]] = self.series(entry["key"], force=force)
        return out

    @staticmethod
    def latest(data: MacroSeries) -> tuple[str, float] | None:
        if not data.observations:
            return None
        obs = data.observations[-1]
        return obs.date, obs.value

    @staticmethod
    def tail(data: MacroSeries, n: int = 60) -> list[MacroObservation]:
        return data.observations[-n:]

    def yield_curve(self, force: bool = False) -> DataResult[dict[str, Any]]:
        points: list[dict[str, Any]] = []
        errors: list[str] = []
        fetched_at = ""
        status = "live"
        for tenor, key in YIELD_CURVE_KEYS.items():
            if not any(c["key"] == key for c in self.catalog()):
                continue
            result = self.series(key, force=force)
            if result.data is None or not result.data.observations:
                errors.append(f"{key}: {result.message or 'no data'}")
                status = STATUS_ERROR if status == "live" and not points else status
                continue
            obs = result.data.observations[-1]
            points.append(
                {"tenor": tenor, "date": obs.date, "value": obs.value, "title": result.data.title}
            )
            fetched_at = result.fetched_at or fetched_at
            if result.status in ("stale", "cached") and status == "live":
                status = result.status
        if len(points) < 2:
            return DataResult(
                data=None,
                status=STATUS_ERROR if not points else status,
                message="; ".join(errors) or "insufficient yield curve data",
                provider=self.name,
                fetched_at=fetched_at,
            )
        points.sort(key=lambda p: p["tenor"])
        return DataResult(
            data={"points": points, "errors": errors},
            status=status,
            message="; ".join(errors) or None,
            provider=self.name,
            fetched_at=fetched_at,
        )

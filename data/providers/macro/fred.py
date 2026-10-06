from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from data.models import MacroObservation, MacroSeries
from data.providers.base import ConfigError, HttpClient, MacroDataProvider, ProviderError
from database.sqlite_db import utcnow_iso


class FredMacroProvider(MacroDataProvider):
    name = "fred"

    def __init__(self, config: dict[str, Any]):
        self.base_url = str(config.get("base_url", "https://api.stlouisfed.org/fred")).rstrip("/")
        self.api_key = config.get("_api_key")
        network = config.get("_network", {})
        self.client = HttpClient(
            user_agent=str(network.get("user_agent", "personal-financial-terminal/0.1")),
            timeout=float(network.get("timeout_seconds", 10)),
            retries=int(network.get("retries", 2)),
        )

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def series(self, series_id: str, limit: int = 800) -> MacroSeries:
        if not self.api_key:
            raise ConfigError("FRED API key not configured (set FRED_API_KEY or providers.fred.api_key)")
        data = self.client.get_json(
            f"{self.base_url}/series/observations",
            params={
                "series_id": series_id,
                "api_key": self.api_key,
                "file_type": "json",
                "sort_order": "desc",
                "limit": limit,
            },
        )
        meta = self.client.get_json(
            f"{self.base_url}/series",
            params={"series_id": series_id, "api_key": self.api_key, "file_type": "json"},
        ).get("seriess") or []
        title = meta[0].get("title", series_id) if meta else series_id
        units = meta[0].get("units", "") if meta else ""
        observations = []
        for entry in data.get("observations") or []:
            raw = entry.get("value")
            if raw in (None, "."):
                continue
            try:
                value = float(raw)
            except (TypeError, ValueError):
                continue
            observations.append(MacroObservation(date=entry.get("date", ""), value=value))
        observations.reverse()
        if not observations:
            raise ProviderError(f"no observations for series {series_id}")
        return MacroSeries(
            id=series_id,
            title=title,
            units=units,
            source=self.name,
            observations=observations,
            fetched_at=utcnow_iso(),
        )

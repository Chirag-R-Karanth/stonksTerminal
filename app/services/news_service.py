from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timedelta, timezone
from typing import Any

from app.config import Config
from data.models import STATUS_CACHED, STATUS_ERROR, STATUS_LIVE, STATUS_STALE, DataResult, NewsItem
from data.providers.base import NewsProvider
from database.repositories import NewsCacheRepo
from database.sqlite_db import utcnow_iso

log = logging.getLogger(__name__)


class NewsService:
    def __init__(self, provider: NewsProvider, repo: NewsCacheRepo, config: Config):
        self.provider = provider
        self.repo = repo
        self.config = config
        self.ttl = float(config.get("data.cache.news_ttl_seconds", 300))
        self._lock = threading.Lock()

    @property
    def name(self) -> str:
        return self.provider.name

    def _newest_fetch(self) -> datetime | None:
        row = self.repo.db.query_one("SELECT MAX(fetched_at) AS m FROM news_cache")
        if row is None or not row["m"]:
            return None
        try:
            ts = datetime.fromisoformat(str(row["m"]).replace("Z", "+00:00"))
        except ValueError:
            return None
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts

    def _fresh(self) -> bool:
        newest = self._newest_fetch()
        if newest is None:
            return False
        return (datetime.now(timezone.utc) - newest) <= timedelta(seconds=self.ttl)

    @staticmethod
    def _to_item(row: dict[str, Any]) -> NewsItem:
        return NewsItem(
            id=str(row.get("guid") or row.get("url") or ""),
            title=str(row.get("title") or ""),
            summary=str(row.get("summary") or ""),
            url=str(row.get("url") or ""),
            published_at=row.get("published_at"),
            source=str(row.get("source") or ""),
            category=str(row.get("category") or ""),
            symbols=list(row.get("symbols") or []),
        )

    def headlines(
        self,
        symbols: list[str] | None = None,
        query: str | None = None,
        limit: int = 60,
        force: bool = False,
    ) -> DataResult[list[NewsItem]]:
        with self._lock:
            if not force and self._fresh():
                rows = self.repo.list(limit=limit, query=query, symbols=symbols)
                if rows:
                    return DataResult(
                        data=[self._to_item(r) for r in rows],
                        status=STATUS_CACHED, provider=self.name,
                        fetched_at=utcnow_iso(),
                    )
            try:
                items = self.provider.headlines(
                    symbols=[s.upper() for s in symbols] if symbols else None,
                    query=query,
                    limit=max(limit * 2, 100),
                )
            except Exception as exc:
                log.warning("news fetch failed: %s", exc)
                rows = self.repo.list(limit=limit, query=query, symbols=symbols)
                if rows:
                    return DataResult(
                        data=[self._to_item(r) for r in rows],
                        status=STATUS_STALE, message=f"live fetch failed: {exc}",
                        provider=self.name, fetched_at=utcnow_iso(),
                    )
                return DataResult(
                    data=None, status=STATUS_ERROR, message=str(exc), provider=self.name,
                )
            payload = [
                {
                    "id": item.id,
                    "title": item.title,
                    "summary": item.summary,
                    "url": item.url,
                    "published_at": item.published_at,
                    "source": item.source,
                    "category": item.category,
                    "symbols": item.symbols,
                }
                for item in items
            ]
            if payload:
                try:
                    self.repo.put_many(payload, provider=self.name)
                    self.repo.prune()
                except Exception as exc:
                    log.warning("news cache write failed: %s", exc)
            if query or symbols:
                rows = self.repo.list(limit=limit, query=query, symbols=symbols)
                merged = [self._to_item(r) for r in rows]
                known = {i.id for i in merged}
                merged.extend(i for i in items if i.id not in known)
                items = merged[:limit]
            return DataResult(
                data=items[:limit], status=STATUS_LIVE, provider=self.name, fetched_at=utcnow_iso(),
            )

    def rows(
        self,
        symbols: list[str] | None = None,
        query: str | None = None,
        limit: int = 60,
        force: bool = False,
    ) -> DataResult[list[dict[str, Any]]]:
        result = self.headlines(symbols=symbols, query=query, limit=limit, force=force)
        if result.data is None:
            return DataResult(
                data=None, status=result.status, message=result.message,
                provider=result.provider, fetched_at=result.fetched_at,
            )
        rows = []
        for item in result.data:
            published = item.published_at or ""
            try:
                stamp = datetime.fromisoformat(published.replace("Z", "+00:00"))
                display = stamp.strftime("%Y-%m-%d %H:%M")
            except (ValueError, AttributeError):
                display = published
            rows.append(
                {
                    "id": item.id,
                    "time": display,
                    "source": item.source,
                    "title": item.title,
                    "symbols": ", ".join(item.symbols),
                    "summary": item.summary,
                    "url": item.url,
                }
            )
        return DataResult(
            data=rows, status=result.status, message=result.message,
            provider=result.provider, fetched_at=result.fetched_at,
        )

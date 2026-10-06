from __future__ import annotations

import hashlib
import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

from data.models import NewsItem
from data.providers.base import HttpClient, NewsProvider, ProviderError

log = logging.getLogger(__name__)

TOKEN_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,11}$")
_NS = {"atom": "http://www.w3.org/2005/Atom"}


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _parse_date(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip()
    try:
        dt = parsedate_to_datetime(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat(timespec="seconds")
    except (TypeError, ValueError):
        pass
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat(timespec="seconds")
    except ValueError:
        return None


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", " ", text or "").strip()


class RssNewsProvider(NewsProvider):
    name = "yahoo_rss"

    def __init__(self, config: dict[str, Any]):
        self.feeds = list(config.get("feeds", []))
        network = config.get("_network", {})
        self.client = HttpClient(
            user_agent=str(network.get("user_agent", "personal-financial-terminal/0.1")),
            timeout=float(network.get("timeout_seconds", 10)),
            retries=int(network.get("retries", 1)),
        )
        self.search_url = str(config.get("_search_url", "https://query1.finance.yahoo.com/v1/finance/search"))

    def headlines(
        self,
        symbols: list[str] | None = None,
        query: str | None = None,
        limit: int = 50,
    ) -> list[NewsItem]:
        items: list[NewsItem] = []
        if symbols:
            items.extend(self._symbol_news(symbols))
        for feed in self.feeds:
            try:
                items.extend(self._feed_news(feed))
            except Exception as exc:
                log.warning("news feed %s failed: %s", feed.get("name"), exc)
        items = self._dedupe(items)
        if symbols:
            wanted = {s.upper().lstrip("$") for s in symbols}
            tagged = [i for i in items if wanted.intersection({s.upper() for s in i.symbols})]
            if tagged:
                items = tagged + [i for i in items if i not in tagged]
        if query:
            needle = query.lower()
            items = [
                i for i in items
                if needle in (i.title + " " + i.summary).lower()
                or needle in {s.lower() for s in i.symbols}
            ]
        items.sort(key=lambda i: i.published_at or "", reverse=True)
        return items[:limit]

    def _symbol_news(self, symbols: list[str]) -> list[NewsItem]:
        items: list[NewsItem] = []
        for symbol in symbols[:6]:
            try:
                data = self.client.get_json(
                    self.search_url,
                    params={"q": symbol, "newsCount": 12, "quotesCount": 0, "listsCount": 0},
                )
            except Exception as exc:
                log.warning("symbol news for %s failed: %s", symbol, exc)
                continue
            for entry in data.get("news") or []:
                published = entry.get("providerPublishTime")
                link = entry.get("link") or ""
                guid = entry.get("uuid") or hashlib.sha1(f"{link}{entry.get('title')}".encode()).hexdigest()
                related = [s for s in (entry.get("relatedTickers") or []) if isinstance(s, str)]
                items.append(
                    NewsItem(
                        id=guid,
                        title=str(entry.get("title") or ""),
                        summary="",
                        url=link,
                        published_at=datetime.fromtimestamp(int(published), tz=timezone.utc).isoformat(timespec="seconds")
                        if published
                        else None,
                        source=str(entry.get("publisher") or ""),
                        category="symbol",
                        symbols=related,
                    )
                )
        return items

    def _feed_news(self, feed: dict[str, Any]) -> list[NewsItem]:
        url = str(feed.get("url", ""))
        if not url:
            return []
        response = self.client.get(url)
        if response.status_code >= 400:
            raise ProviderError(f"feed HTTP {response.status_code}: {url}")
        try:
            root = ET.fromstring(response.content)
        except ET.ParseError as exc:
            raise ProviderError(f"feed parse error: {url}") from exc
        items: list[NewsItem] = []
        source_name = str(feed.get("name") or url)
        category = str(feed.get("category") or "general")
        channel_items = root.findall("./channel/item")
        if channel_items:
            for node in channel_items:
                items.append(self._rss_item(node, source_name, category))
        else:
            for node in root.findall("atom:entry", _NS):
                items.append(self._atom_item(node, source_name, category))
        return [i for i in items if i.title]

    def _rss_item(self, node: ET.Element, source: str, category: str) -> NewsItem:
        title = (node.findtext("title") or "").strip()
        link = (node.findtext("link") or "").strip()
        guid = (node.findtext("guid") or link or title).strip()
        summary = _strip_html(node.findtext("description") or "")[:400]
        published = _parse_date(node.findtext("pubDate"))
        return NewsItem(
            id=hashlib.sha1(guid.encode()).hexdigest(),
            title=title,
            summary=summary,
            url=link,
            published_at=published,
            source=source,
            category=category,
            symbols=self._tag_symbols(f"{title} {summary}"),
        )

    def _atom_item(self, node: ET.Element, source: str, category: str) -> NewsItem:
        title = (node.findtext("atom:title", namespaces=_NS) or "").strip()
        link_node = node.find("atom:link", _NS)
        link = link_node.get("href", "") if link_node is not None else ""
        node_id = (node.findtext("atom:id", namespaces=_NS) or link or title).strip()
        summary = _strip_html(node.findtext("atom:summary", namespaces=_NS) or node.findtext("atom:content", namespaces=_NS) or "")[:400]
        published = _parse_date(node.findtext("atom:published", namespaces=_NS) or node.findtext("atom:updated", namespaces=_NS))
        return NewsItem(
            id=hashlib.sha1(node_id.encode()).hexdigest(),
            title=title,
            summary=summary,
            url=link,
            published_at=published,
            source=source,
            category=category,
            symbols=self._tag_symbols(f"{title} {summary}"),
        )

    @staticmethod
    def _tag_symbols(text: str) -> list[str]:
        found: set[str] = set()
        for token in re.findall(r"\b[A-Z][A-Z0-9.\-]{1,10}\b", text):
            if TOKEN_RE.match(token) and token not in {"THE", "AND", "FOR", "ALL", "NEW", "USA", "USD", "GDP", "IPO", "CEO", "CFO", "ETF", "ETFs", "FED", "RBI", "NIFTY", "SENSEX", "OPEN", "HIGH", "LOW"}:
                found.add(token)
        return sorted(found)

    @staticmethod
    def _dedupe(items: list[NewsItem]) -> list[NewsItem]:
        seen: set[str] = set()
        out: list[NewsItem] = []
        for item in items:
            key = item.url or re.sub(r"\W+", "", item.title.lower())[:80]
            if key in seen:
                continue
            seen.add(key)
            out.append(item)
        return out

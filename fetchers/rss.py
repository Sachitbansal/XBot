"""RSS/Atom feeds listed in config.RSS_FEEDS."""
import logging
import time
from datetime import datetime, timedelta, timezone

import feedparser
from bs4 import BeautifulSoup

import config
from fetchers import http_client, make_item

log = logging.getLogger(__name__)


def _published(entry) -> datetime | None:
    t = entry.get("published_parsed") or entry.get("updated_parsed")
    return datetime(*t[:6], tzinfo=timezone.utc) if t else None


def fetch() -> list[dict]:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=config.RSS_LOOKBACK_HOURS)
    items = []
    with http_client() as client:
        for name, url in config.RSS_FEEDS.items():
            try:
                resp = client.get(url)
                if resp.status_code == 429:
                    reset = float(resp.headers.get("x-ratelimit-reset") or config.RSS_RETRY_DELAY_SECONDS)
                    time.sleep(min(reset + 1, config.RSS_MAX_RETRY_WAIT_SECONDS))
                    resp = client.get(url)
                resp.raise_for_status()
            except Exception as e:
                log.warning("RSS feed %s failed: %s", name, e)
                continue
            feed = feedparser.parse(resp.content)
            for e in feed.entries[: config.RSS_MAX_PER_FEED]:
                published = _published(e)
                if published and published < cutoff:
                    continue
                summary = BeautifulSoup(e.get("summary", ""), "html.parser").get_text(" ", strip=True)
                items.append(make_item(
                    f"rss:{name}",
                    e.get("link", ""),
                    e.get("title", ""),
                    raw_content=summary[:3000],
                    author=e.get("author"),
                    published_at=published,
                    metadata={"feed": name},
                ))
    return [i for i in items if i["source_url"] and i["title"]]

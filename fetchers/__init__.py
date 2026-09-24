"""Source fetchers. Each module exposes `fetch() -> list[dict]` of RawItem-shaped dicts."""
from datetime import datetime

import httpx

import config


def http_client() -> httpx.Client:
    return httpx.Client(timeout=config.HTTP_TIMEOUT_SECONDS, follow_redirects=True,
                        headers={"User-Agent": config.USER_AGENT})


def make_item(source: str, source_url: str, title: str, *, raw_content: str | None = None,
              author: str | None = None, published_at: datetime | None = None,
              metadata: dict | None = None) -> dict:
    """Common RawItem shape (raw_items columns minus id/fetched_at/content_hash)."""
    return {
        "source": source,
        "source_url": source_url,
        "title": (title or "").strip(),
        "raw_content": (raw_content or "").strip() or None,
        "author": author,
        "published_at": published_at,
        "metadata": metadata or {},
    }


def get_fetchers() -> dict:
    from fetchers import arxiv, github_trending, hackernews, rss, x_trending_search
    return {
        "hackernews": hackernews.fetch,
        "arxiv": arxiv.fetch,
        "github_trending": github_trending.fetch,
        "rss": rss.fetch,
        "x_search": x_trending_search.fetch,
    }

"""X-trending via web search. Provider is swappable through config.SEARCH_PROVIDER.

Results that are real X post URLs (x.com/<user>/status/<id>) get `author` set and
metadata.x_post_url populated — those are what feed quote_post drafts.
"""
import logging
import re

import config
from fetchers import http_client, make_item

log = logging.getLogger(__name__)

X_POST_RE = re.compile(r"https?://(?:www\.|mobile\.)?(?:x|twitter)\.com/([A-Za-z0-9_]{1,15})/status/(\d+)")


def _brave(client, query: str) -> list[dict]:
    resp = client.get("https://api.search.brave.com/res/v1/web/search",
                      params={"q": query, "count": config.X_SEARCH_RESULTS_PER_QUERY, "freshness": "pd"},
                      headers={"X-Subscription-Token": config.BRAVE_API_KEY, "Accept": "application/json"})
    resp.raise_for_status()
    return [{"url": r.get("url"), "title": r.get("title"), "snippet": r.get("description")}
            for r in resp.json().get("web", {}).get("results", [])]


def _serpapi(client, query: str) -> list[dict]:
    resp = client.get("https://serpapi.com/search.json",
                      params={"engine": "google", "q": query, "api_key": config.SERPAPI_KEY,
                              "num": config.X_SEARCH_RESULTS_PER_QUERY, "tbs": "qdr:d"})
    resp.raise_for_status()
    return [{"url": r.get("link"), "title": r.get("title"), "snippet": r.get("snippet")}
            for r in resp.json().get("organic_results", [])]


def _google_cse(client, query: str) -> list[dict]:
    resp = client.get("https://www.googleapis.com/customsearch/v1",
                      params={"key": config.GOOGLE_CSE_KEY, "cx": config.GOOGLE_CSE_CX, "q": query,
                              "num": min(config.X_SEARCH_RESULTS_PER_QUERY, 10), "dateRestrict": "d1"})
    resp.raise_for_status()
    return [{"url": r.get("link"), "title": r.get("title"), "snippet": r.get("snippet")}
            for r in resp.json().get("items", [])]


PROVIDERS = {"brave": _brave, "serpapi": _serpapi, "google_cse": _google_cse}


def search(query: str) -> list[dict]:
    """Provider-agnostic search: returns [{url, title, snippet}]."""
    provider = PROVIDERS.get(config.SEARCH_PROVIDER)
    if provider is None:
        return []
    with http_client() as client:
        return provider(client, query)


def fetch() -> list[dict]:
    if config.SEARCH_PROVIDER not in PROVIDERS:
        log.info("x_search disabled (SEARCH_PROVIDER=%s)", config.SEARCH_PROVIDER)
        return []

    items = []
    for query in config.X_SEARCH_QUERIES:
        try:
            results = search(query)
        except Exception as e:
            log.warning("search %r failed: %s", query, e)
            continue
        for r in results:
            if not r.get("url") or not r.get("title"):
                continue
            m = X_POST_RE.match(r["url"])
            url = f"https://x.com/{m.group(1)}/status/{m.group(2)}" if m else r["url"]
            items.append(make_item(
                f"x_search:{query}",
                url,
                r["title"],
                raw_content=r.get("snippet"),
                author=f"@{m.group(1)}" if m else None,
                metadata={"provider": config.SEARCH_PROVIDER,
                          "x_post_url": url if m else None},
            ))
    return items

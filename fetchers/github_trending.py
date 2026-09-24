"""GitHub trending (daily), scraped from github.com/trending."""
import logging
import re

from bs4 import BeautifulSoup

import config
from fetchers import http_client, make_item

log = logging.getLogger(__name__)


def _int(text: str | None) -> int | None:
    digits = re.sub(r"[^\d]", "", text or "")
    return int(digits) if digits else None


def _parse(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    items = []
    for art in soup.select("article.Box-row")[: config.GITHUB_TRENDING_MAX]:
        link = art.select_one("h2 a")
        if not link:
            continue
        repo = "".join(link.get_text().split())  # "owner/name"
        desc = art.select_one("p")
        lang = art.select_one('[itemprop="programmingLanguage"]')
        stars = art.select_one('a[href$="/stargazers"]')
        today = art.find(string=re.compile(r"stars? (today|this week)"))
        items.append(make_item(
            "github_trending",
            f"https://github.com/{repo}",
            repo,
            raw_content=desc.get_text(strip=True) if desc else None,
            author=repo.split("/")[0],
            metadata={"language": lang.get_text(strip=True) if lang else None,
                      "stars": _int(stars.get_text() if stars else None),
                      "stars_today": _int(str(today) if today else None)},
        ))
    return items


def fetch() -> list[dict]:
    items = []
    with http_client() as client:
        for url in config.GITHUB_TRENDING_URLS:
            try:
                resp = client.get(url)
                resp.raise_for_status()
            except Exception as e:
                log.warning("GitHub trending %s failed: %s", url, e)
                continue
            items += _parse(resp.text)
    return items


def fetch_readme(repo: str) -> str | None:
    """Plain-text README excerpt via the GitHub API (60 req/h unauthenticated). None on failure."""
    try:
        with http_client() as client:
            resp = client.get(f"https://api.github.com/repos/{repo}/readme",
                              headers={"Accept": "application/vnd.github.raw"})
            resp.raise_for_status()
    except Exception as e:
        log.warning("README fetch failed for %s: %s", repo, e)
        return None
    text = re.sub(r"<[^>]+>|!\[[^\]]*\]\([^)]*\)", " ", resp.text)  # drop HTML tags + images
    lines = (" ".join(line.split()) for line in text.splitlines())
    text = "\n".join(line for line in lines if len(line) > 2)  # drop blank / separator lines
    return text[: config.GITHUB_README_CHARS] or None

"""GitHub trending (daily), scraped from github.com/trending."""
import re

from bs4 import BeautifulSoup

import config
from fetchers import http_client, make_item


def _int(text: str | None) -> int | None:
    digits = re.sub(r"[^\d]", "", text or "")
    return int(digits) if digits else None


def fetch() -> list[dict]:
    with http_client() as client:
        resp = client.get(config.GITHUB_TRENDING_URL)
        resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

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

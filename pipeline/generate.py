"""Draft generation for items that cleared the threshold. One LLM call per item, all angles at once."""
import json
import logging

import config
import db
import llm
from fetchers import github_trending

log = logging.getLogger(__name__)

# Intents, not templates: literal patterns get copied verbatim and every post sounds the same.
ANGLE_GUIDES = {
    "technical_insight": "Point out the non-obvious consequence people are missing — framed as what it "
                         "changes for devs/builders, not how it works internally.",
    "contrarian": "Push back on the obvious reading or the hype. A real opinion someone could argue with.",
    "builder_pov": "First-person builder take: what you'd do with this, swap for it, or build on top of it.",
    "short_punchy": f"One line, max {config.SHORT_PUNCHY_MAX_CHARS} characters. Hits like a headline.",
    "quote_post": "Written to quote the original X post. Add your take; don't restate the post.",
}

BANNED = "\n".join(f'  - "{p}"' for p in config.BANNED_PHRASES)

SYSTEM = f"""You ghostwrite X (Twitter) posts for a developer/builder growing their audience.
Their niche: {config.NICHE}.
Goal: {config.POST_GOAL}.
Style: {config.STYLE_INSTRUCTION}.
Rules:
- Each post stands alone, under {config.X_MAX_CHARS} characters unless stated otherwise.
- Write for devs and builders scrolling fast, not researchers. No academic tone,
  no stacking technical terms, no explaining methodology. One concrete, striking detail
  beats three accurate ones.
- The first few words must earn the stop-scroll: a number, a bold claim, a stake, a question.
- Sound like a real person posting, not a content template. Every post in the set must open
  differently and use a different sentence structure. Vary rhythm: fragments, questions,
  lists, one-liners.
- Never use these stock phrases (or close variants):
{BANNED}
- Discussion hook: usually ONE post in the set (pick whichever angle it fits best, at most
  two) should end with a genuine question to the audience — one devs would actually want to
  answer from their own experience: which tool they'd pick, whether they've hit this problem,
  where they draw the line, what they'd build with it. It must be specific to this item. The
  other posts make their point and stop. Skip the question only if nothing genuine fits.
- No hashtags. At most one emoji, usually zero.
- Be specific (name the thing, the number), but never invent facts not in the source.
- Don't include links; they get attached separately.
- If an angle genuinely doesn't fit this item, return null for it rather than forcing it."""

PAPER_NOTE = (
    "NOTE: This is a research paper. The author has only seen the title and abstract, NOT "
    "the full paper. Never write as if they read it, ran it, or know details beyond the "
    "abstract (no \"I read\", \"after digging into\", \"the paper shows in section X\"). Frame it "
    "as news: \"New research: ...\", \"Researchers just found ...\", \"A new paper claims ...\". "
    "Focus on the headline takeaway and why regular tech people should care.\n\n"
)


REPO_NOTE = (
    "NOTE: This is a trending repo/model. Write it the way repo-spotlight posts that blow up on "
    "dev X do: say plainly what it does and who it's for, lead with the traction if notable "
    "(stars gained today, total stars), and why devs are jumping on it — what it replaces, "
    "saves, or unlocks. Use only what the README/description actually says.\n\n"
)
REPO_SOURCES = ("github_trending", "hf_models")


def source_note(item: dict) -> str:
    if item["source"] in config.SUMMARY_ONLY_SOURCES:
        return PAPER_NOTE
    if item["source"] in REPO_SOURCES:
        return REPO_NOTE
    return ""


def enrich(item: dict) -> dict:
    """Give thin items more substance before generation (repos: README excerpt)."""
    if item["source"] == "github_trending":
        readme = github_trending.fetch_readme(item["title"])
        if readme:
            desc = item.get("raw_content") or ""
            return {**item, "raw_content": f"{desc}\n\nREADME excerpt:\n{readme}"}
    return item


def banned_phrase(text: str) -> str | None:
    """First banned stock phrase found in text (case/apostrophe-insensitive), else None."""
    norm = text.lower().replace("\u2019", "'")
    return next((p for p in config.BANNED_PHRASES if p.lower() in norm), None)


def angles_for(item: dict) -> list[str]:
    """Enabled angles; quote_post only when a real X post URL exists."""
    meta = item.get("metadata") or {}
    angles = [a for a, on in config.ANGLES.items() if on]
    if not (meta.get("x_post_url") and item.get("author")):
        angles = [a for a in angles if a != "quote_post"]
    return angles


def build_prompt(item: dict, angles: list[str]) -> str:
    guides = "\n".join(f"- {a}: {ANGLE_GUIDES[a]}" for a in angles)
    keys = ", ".join(f'"{a}": "..." or null' for a in angles)
    return (
        source_note(item) +
        f"Source: {item['source']}\n"
        f"Title: {item['title']}\n"
        f"URL: {item['source_url']}\n"
        f"Author: {item.get('author') or 'unknown'}\n"
        f"Signals: {json.dumps(item.get('metadata') or {}, default=str)}\n"
        f"Content: {(item.get('raw_content') or '(none)')[:3000]}\n\n"
        f"Write one post per angle:\n{guides}\n\n"
        f"Respond with JSON only: {{{keys}}}"
    )


def generate_for_item(conn, item: dict) -> list[str]:
    """Generate + persist drafts for one item. Returns new draft ids."""
    angles = angles_for(item)
    if not angles:
        return []
    content, model = llm.generate(SYSTEM, build_prompt(enrich(item), angles), json_mode=True)
    drafts = llm.parse_json(content)

    ids = []
    for angle in angles:
        text = drafts.get(angle)
        if not isinstance(text, str) or not text.strip():
            continue
        text = text.strip().strip('"').strip()
        hit = banned_phrase(text)
        if hit:
            log.info("dropped %s draft (stock phrase %r): %s", angle, hit, text[:80])
            continue
        quote_url = (item.get("metadata") or {}).get("x_post_url") if angle == "quote_post" else None
        ids.append(db.insert_draft(conn, item["id"], angle, text, model, quote_url))
    return ids


def generate_pending(conn) -> dict:
    items = db.items_awaiting_drafts(conn, config.THRESHOLD, config.MIN_RELEVANCE_TO_DRAFT,
                                     config.MAX_ITEMS_TO_DRAFT_PER_CYCLE)
    stats = {"items": 0, "drafts": 0, "failed": 0}
    for item in items:
        try:
            ids = generate_for_item(conn, item)
            conn.commit()
        except Exception as e:
            conn.rollback()
            stats["failed"] += 1
            log.warning("generation failed for %s (%s): %s", item["id"], item["title"][:60], e)
            continue
        stats["items"] += 1
        stats["drafts"] += len(ids)
        log.info("generated %d drafts for: %s", len(ids), item["title"][:80])
    return stats

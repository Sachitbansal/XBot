"""Draft generation for items that cleared the threshold. One LLM call per item, all angles at once."""
import json
import logging

import config
import db
import llm

log = logging.getLogger(__name__)

ANGLE_GUIDES = {
    "technical_insight": 'Pattern: "The interesting part about X isn\'t [obvious thing]. It\'s [specific implication]."',
    "contrarian": 'Pattern: "Everyone\'s talking about X. The more important story is Y."',
    "builder_pov": 'Pattern: "If I were building ___ today, I\'d use X instead of Y. Here\'s why."',
    "short_punchy": f"A single one-liner, max {config.SHORT_PUNCHY_MAX_CHARS} characters.",
    "quote_post": 'Written to quote the original X post. Format: "My take: ___". Don\'t restate the post.',
}

SYSTEM = f"""You ghostwrite X (Twitter) posts for a developer/builder.
Style: {config.STYLE_INSTRUCTION}.
Rules:
- Each post stands alone, under {config.X_MAX_CHARS} characters unless stated otherwise.
- No hashtags. At most one emoji, usually zero. No "🚀", no "Game changer", no "Let's dive in".
- Be specific: name the actual thing, number, or mechanism. Never invent facts not in the source.
- Don't include links; they get attached separately.
- If an angle genuinely doesn't fit this item, return null for it rather than forcing it."""


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
    content, model = llm.generate(SYSTEM, build_prompt(item, angles), json_mode=True)
    drafts = llm.parse_json(content)

    ids = []
    for angle in angles:
        text = drafts.get(angle)
        if not isinstance(text, str) or not text.strip():
            continue
        text = text.strip().strip('"').strip()
        quote_url = (item.get("metadata") or {}).get("x_post_url") if angle == "quote_post" else None
        ids.append(db.insert_draft(conn, item["id"], angle, text, model, quote_url))
    return ids


def generate_pending(conn) -> dict:
    items = db.items_awaiting_drafts(conn, config.MAX_ITEMS_TO_DRAFT_PER_CYCLE)
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

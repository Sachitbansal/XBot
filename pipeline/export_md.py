"""Build-phase output: append drafts to a per-day markdown file (output/drafts/YYYY-MM-DD.md).

Each item gets a section with its score breakdown; each draft shows its short id so
decisions can be logged with `python review.py` (or the Telegram buttons).
"""
import logging
from datetime import datetime
from pathlib import Path

import config

log = logging.getLogger(__name__)

AXES = [("virality_score", "vir"), ("novelty_score", "nov"), ("technical_score", "tech"),
        ("relevance_score", "rel"), ("discussion_score", "disc")]


def render_item(drafts: list[dict]) -> str:
    d0 = drafts[0]
    breakdown = " · ".join(f"{label} {d0[col]}" for col, label in AXES if d0.get(col) is not None)
    score = f"**{float(d0['composite_score']):.2f}**" if d0.get("composite_score") is not None else "?"
    lines = [
        f"## {d0.get('title') or '(item deleted)'}",
        "",
        f"- {d0.get('source')} · {d0.get('source_url')}",
        f"- score {score} ({breakdown})",
        f"- generated {d0['generated_at'].astimezone():%H:%M} · {d0['generation_model']}",
        "",
    ]
    for d in drafts:
        lines += [f"### {d['angle_type']} · `{str(d['id'])[:8]}` · {len(d['ai_draft'])} chars", ""]
        if d.get("quote_target_url"):
            lines += [f"Quote: {d['quote_target_url']}", ""]
        lines += [f"> {line}" if line else ">" for line in d["ai_draft"].splitlines()] + [""]
    return "\n".join(lines) + "\n---\n\n"


def write(drafts: list[dict]) -> Path | None:
    """Append drafts (grouped by item) to today's file. Pure file I/O; caller marks delivery."""
    if not drafts:
        return None
    out_dir = Path(config.DRAFTS_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{datetime.now():%Y-%m-%d}.md"

    by_item: dict = {}
    for d in drafts:
        by_item.setdefault(d["raw_item_id"], []).append(d)
    chunks = [render_item(group) for group in by_item.values()]

    new_file = not path.exists()
    with path.open("a", encoding="utf-8") as f:
        if new_file:
            f.write(f"# Drafts {datetime.now():%Y-%m-%d}\n\nReview: `python review.py` or Telegram\n\n")
        f.write("".join(chunks))
    log.info("wrote %d drafts to %s", len(drafts), path)
    return path

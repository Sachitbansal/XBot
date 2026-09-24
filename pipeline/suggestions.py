"""Sachit's /suggest feedback → prompt guidance, consolidated by an LLM when it grows too long."""
import logging

import config
import db
import llm

log = logging.getLogger(__name__)

CONSOLIDATE_SYSTEM = f"""You maintain a short list of instructions a creator has given to the AI
that writes and picks their X posts. Merge the existing summary and the new suggestions into
one concise, deduplicated list of imperative bullet points.
- When suggestions conflict, the newer one wins (new suggestions are listed oldest → newest,
  all newer than the existing summary).
- Keep every distinct preference; drop only exact repeats and superseded ones.
- Keep the creator's specifics (names, topics, words to avoid). No commentary.
- Stay under {config.SUGGESTIONS_SUMMARY_TARGET_CHARS} characters.
Output only the bullet list."""


def _pieces(conn) -> tuple[dict | None, list[dict]]:
    return db.latest_suggestion_summary(conn), db.unsummarized_suggestions(conn)


def render(summary: dict | None, pending: list[dict]) -> str:
    parts = []
    if summary:
        parts.append(summary["summary"].strip())
    parts += [f"- {s['text'].strip()}" for s in pending]
    return "\n".join(parts)


def active_guidance(conn) -> str:
    """Text injected into prompts ('' when there's no feedback yet)."""
    return render(*_pieces(conn))


def maybe_consolidate(conn) -> bool:
    """If guidance exceeds the limit, fold it into a new summary. Commits. Returns True if it ran."""
    summary, pending = _pieces(conn)
    if not pending or len(render(summary, pending)) <= config.SUGGESTIONS_MAX_CHARS:
        return False
    user = (f"Existing summary:\n{summary['summary'] if summary else '(none)'}\n\n"
            "New suggestions (oldest → newest):\n" + "\n".join(f"- {s['text']}" for s in pending))
    text, model = llm.generate(CONSOLIDATE_SYSTEM, user)
    db.insert_suggestion_summary(conn, text.strip(), model, [s["id"] for s in pending])
    conn.commit()
    log.info("consolidated %d suggestions into summary (%d chars)", len(pending), len(text))
    return True


def add(conn, text: str) -> dict:
    """Store a suggestion, consolidating if needed. Returns {consolidated, guidance}."""
    db.insert_suggestion(conn, text.strip())
    conn.commit()
    consolidated = maybe_consolidate(conn)
    return {"consolidated": consolidated, "guidance": active_guidance(conn)}


def prompt_block(conn) -> str:
    """Section appended to system prompts; empty when there's no feedback."""
    g = active_guidance(conn)
    if not g:
        return ""
    return ("\n\nThe creator's own feedback — follow it; it overrides the defaults above "
            f"where they conflict:\n{g}")

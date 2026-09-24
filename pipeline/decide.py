"""Approve / edit / reject → decisions + edit_pairs rows. Pure DB logic, no Telegram."""
import db

ACTIONS = {"a": "approved_as_is", "e": "edited", "r": "rejected"}


class AlreadyDecided(Exception):
    pass


def word_edit_distance(a: str, b: str) -> int:
    """Levenshtein distance over words (insert/delete/substitute one word = 1)."""
    x, y = a.split(), b.split()
    prev = list(range(len(y) + 1))
    for i, wx in enumerate(x, 1):
        cur = [i]
        for j, wy in enumerate(y, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (wx != wy)))
        prev = cur
    return prev[-1]


def decide(conn, draft_id: str, decision: str, final_version: str | None = None) -> dict:
    """Record one decision for a draft. Commits. Raises AlreadyDecided / LookupError."""
    draft = db.get_draft(conn, draft_id)
    if draft is None:
        raise LookupError(f"draft {draft_id} not found")
    if db.draft_has_decision(conn, draft_id):
        raise AlreadyDecided(draft_id)

    if decision == "approved_as_is":
        final_version, distance = draft["ai_draft"], 0
    elif decision == "edited":
        if not final_version or not final_version.strip():
            raise ValueError("edited decision needs final_version")
        final_version = final_version.strip()
        distance = word_edit_distance(draft["ai_draft"], final_version)
        # Sending back the identical text counts as an approval, not an edit.
        if distance == 0:
            decision = "approved_as_is"
    elif decision == "rejected":
        final_version, distance = None, None
    else:
        raise ValueError(f"unknown decision {decision!r}")

    decision_id = db.record_decision(conn, draft, decision, final_version, distance)
    conn.commit()
    return {"decision_id": decision_id, "decision": decision, "draft": draft,
            "final_version": final_version, "edit_distance": distance}

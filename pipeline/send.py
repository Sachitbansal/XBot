"""Send unsent drafts to Telegram with Approve / Edit / Reject buttons.

Uses the plain Bot API over HTTP so run_cycle stays sync and doesn't need the bot process.
Unsent drafts (e.g. Telegram down, token missing) are retried on the next cycle.
"""
import html
import logging

import httpx

import config
import db

log = logging.getLogger(__name__)

ANGLE_LABELS = {
    "technical_insight": "🔬 technical insight",
    "contrarian": "🔄 contrarian",
    "builder_pov": "🛠 builder POV",
    "short_punchy": "⚡ short & punchy",
    "quote_post": "💬 quote post",
}


def format_draft(draft: dict) -> str:
    score = draft.get("composite_score")
    header = f"<b>{ANGLE_LABELS.get(draft['angle_type'], draft['angle_type'])}</b>"
    if score is not None:
        header += f" · score {float(score):.2f}"
    lines = [
        header,
        f"<a href=\"{html.escape(draft.get('source_url') or '')}\">{html.escape(draft.get('title') or '')}</a>"
        f" <i>({html.escape(draft.get('source') or '')})</i>",
    ]
    if draft.get("quote_target_url"):
        lines.append(f"Quote: {html.escape(draft['quote_target_url'])}")
    lines += ["", html.escape(draft["ai_draft"]), "", f"<i>{len(draft['ai_draft'])} chars</i>"]
    return "\n".join(lines)


def keyboard(draft_id: str) -> dict:
    return {"inline_keyboard": [[
        {"text": "✅ Approve", "callback_data": f"a:{draft_id}"},
        {"text": "✏️ Edit", "callback_data": f"e:{draft_id}"},
        {"text": "❌ Reject", "callback_data": f"r:{draft_id}"},
    ]]}


def send_message(text: str, reply_markup: dict | None = None) -> int:
    resp = httpx.post(
        f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage",
        json={"chat_id": config.TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML",
              "link_preview_options": {"is_disabled": True}, "reply_markup": reply_markup},
        timeout=config.HTTP_TIMEOUT_SECONDS,
    )
    data = resp.json()
    if not data.get("ok"):
        raise RuntimeError(f"Telegram sendMessage failed: {data.get('description')}")
    return data["result"]["message_id"]


def telegram_configured() -> bool:
    return bool(config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHAT_ID)


def send_pending(conn) -> dict:
    stats = {"sent": 0, "failed": 0}
    if not telegram_configured():
        log.warning("Telegram not configured; skipping send")
        return stats
    drafts = db.unsent_drafts(conn, config.SEND_MAX_DRAFT_AGE_HOURS, config.MAX_DRAFTS_SENT_PER_CYCLE)

    for d in drafts:
        try:
            msg_id = send_message(format_draft(d), keyboard(str(d["id"])))
            db.mark_draft_sent(conn, d["id"], msg_id)
            conn.commit()
            stats["sent"] += 1
        except Exception as e:
            conn.rollback()
            stats["failed"] += 1
            log.warning("send failed for draft %s: %s", d["id"], e)
    return stats

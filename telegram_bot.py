"""Long-running Telegram listener: Approve / Edit / Reject on drafts sent by run_cycle.py.

- ✅ Approve → decisions(approved_as_is) + edit_pairs(final == ai_draft)
- ✏️ Edit    → bot asks for the edited text; next message becomes final_version
              (replying directly to a draft message with text also counts as an edit)
- ❌ Reject  → decisions(rejected) only

Commands:
- /suggest <text> → store feedback; it's injected into every scoring/generation prompt
- /suggestions    → show the guidance currently in effect
- /post [topic]   → make drafts right now (optionally about a topic)

Only messages from TELEGRAM_CHAT_ID are handled. /start replies with the chat id
so you can find it when first setting up.
"""
import asyncio
import html
import logging
import sys

from telegram import BotCommand, ForceReply, LinkPreviewOptions, Update
from telegram.ext import (Application, CallbackQueryHandler, CommandHandler, ContextTypes,
                          MessageHandler, filters)

import config
import db
from pipeline import decide, on_demand, send, suggestions

log = logging.getLogger("telegram_bot")

STATUS_LABELS = {"approved_as_is": "✅ Approved", "edited": "✏️ Edited", "rejected": "❌ Rejected"}


def authorized(update: Update) -> bool:
    return str(update.effective_chat.id) == str(config.TELEGRAM_CHAT_ID)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        f"chat id: {update.effective_chat.id}\n"
        + ("Authorized. Drafts will show up here." if authorized(update)
           else "Put this in TELEGRAM_CHAT_ID in .env and restart the bot.")
    )


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not authorized(update):
        return
    context.chat_data.pop("awaiting_edit", None)
    await update.message.reply_text("Edit cancelled. Draft is still pending — tap a button again.")


async def suggest(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not authorized(update):
        return
    text = " ".join(context.args).strip()
    if not text:
        await update.message.reply_text("Usage: /suggest <feedback>\ne.g. /suggest fewer questions, more numbers")
        return

    def run():
        with db.connect() as conn:
            return suggestions.add(conn, text)

    result = await asyncio.to_thread(run)
    note = " (condensed old + new feedback into a summary)" if result["consolidated"] else ""
    await update.message.reply_text(f"Saved{note}. Guidance now in effect:\n\n{result['guidance']}")


async def show_suggestions(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not authorized(update):
        return
    with db.connect() as conn:
        guidance = suggestions.active_guidance(conn)
    await update.message.reply_text(guidance or "No suggestions yet. Add one with /suggest <text>.")


async def post_now(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not authorized(update):
        return
    if context.bot_data.get("post_running"):
        await update.message.reply_text("Already making a post — hang on.")
        return
    topic = " ".join(context.args).strip() or None
    await update.message.reply_text(f"On it{f' — topic: {topic}' if topic else ''}. "
                                    "Free models can take a minute or two.")

    def run():
        with db.connect() as conn:
            result = on_demand.make_post(conn, topic)
            sent = send.send_pending(conn, result["draft_ids"])
            return result, sent

    context.bot_data["post_running"] = True
    try:
        result, sent = await asyncio.to_thread(run)
    except on_demand.NothingFound as e:
        await update.message.reply_text(str(e))
        return
    except Exception as e:
        log.exception("/post failed")
        await update.message.reply_text(f"Failed: {e}")
        return
    finally:
        context.bot_data["post_running"] = False
    await update.message.reply_text(
        f"{sent['sent']} drafts for: {result['item']['title'][:120]}"
        + (f" ({sent['failed']} failed to send)" if sent["failed"] else ""))


async def mark_message(context, message_id: int, draft: dict, result: dict) -> None:
    """Replace the draft message's buttons with the outcome."""
    status = STATUS_LABELS[result["decision"]]
    text = f"{status}\n\n{html.escape(draft['ai_draft'])}"
    if result["decision"] == "edited":
        text += (f"\n\n<b>Final</b> ({result['edit_distance']} word edits):\n"
                 f"{html.escape(result['final_version'])}")
    try:
        await context.bot.edit_message_text(chat_id=config.TELEGRAM_CHAT_ID, message_id=message_id,
                                            text=text, parse_mode="HTML",
                                            link_preview_options=LinkPreviewOptions(is_disabled=True))
    except Exception as e:  # message too old / unchanged — decision is already stored
        log.warning("could not edit message %s: %s", message_id, e)


async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not authorized(update):
        await query.answer("Not yours.")
        return
    action, _, draft_id = (query.data or "").partition(":")
    if action not in decide.ACTIONS:
        await query.answer("Unknown action")
        return

    if action == "e":
        with db.connect() as conn:
            if db.draft_has_decision(conn, draft_id):
                await query.answer("Already decided.")
                return
        context.chat_data["awaiting_edit"] = {"draft_id": draft_id,
                                              "message_id": query.message.message_id}
        await query.answer()
        await query.message.reply_text("Send me the edited version (/cancel to abort).",
                                       reply_markup=ForceReply(selective=True))
        return

    try:
        with db.connect() as conn:
            result = decide.decide(conn, draft_id, decide.ACTIONS[action])
    except decide.AlreadyDecided:
        await query.answer("Already decided.")
        return
    except LookupError:
        await query.answer("Draft not found.")
        return
    await query.answer(STATUS_LABELS[result["decision"]])
    await mark_message(context, query.message.message_id, result["draft"], result)


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not authorized(update):
        return
    msg = update.message
    pending = context.chat_data.get("awaiting_edit")

    with db.connect() as conn:
        # Direct reply to a draft message wins over the pending-edit state.
        replied = msg.reply_to_message
        direct = db.get_draft_by_message_id(conn, replied.message_id) if replied else None
        if direct:
            draft_id, message_id = str(direct["id"]), replied.message_id
        elif pending:
            draft_id, message_id = pending["draft_id"], pending["message_id"]
        else:
            await msg.reply_text("No draft awaiting an edit. Tap ✏️ Edit on a draft first.")
            return

        try:
            result = decide.decide(conn, draft_id, "edited", msg.text)
        except decide.AlreadyDecided:
            await msg.reply_text("That draft was already decided.")
            return
        finally:
            if pending and pending["draft_id"] == draft_id:
                context.chat_data.pop("awaiting_edit", None)

    await mark_message(context, message_id, result["draft"], result)
    await msg.reply_text(f"Logged: {STATUS_LABELS[result['decision']]}")


async def set_commands(app: Application) -> None:
    """Populate Telegram's '/' command menu."""
    await app.bot.set_my_commands([
        BotCommand("post", "Make a post now — optional: /post <topic>"),
        BotCommand("suggest", "Give feedback for future posts: /suggest <text>"),
        BotCommand("suggestions", "Show feedback currently in effect"),
        BotCommand("cancel", "Cancel a pending edit"),
    ])


def main() -> None:
    if not config.TELEGRAM_BOT_TOKEN:
        sys.exit("TELEGRAM_BOT_TOKEN not set in .env")
    app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).post_init(set_commands).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("cancel", cancel))
    app.add_handler(CommandHandler("suggest", suggest))
    app.add_handler(CommandHandler("suggestions", show_suggestions))
    app.add_handler(CommandHandler("post", post_now))
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    log.info("bot polling")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, stream=sys.stdout,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    main()

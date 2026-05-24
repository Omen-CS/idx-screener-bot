"""
bot/handlers/bpjs.py
Handles the /bpjs command — manual BPJS scan trigger.

Runs the BPJS scanner and sends results to the user.
"""

import logging
from telegram import Update
from telegram.ext import ContextTypes

from screener.scanner import run_bpjs_scan
from bot.utils.formatter import (
    format_scan_header,
    format_bpjs_alert,
    format_no_results,
    format_error,
    format_disclaimer,
)
from config import settings

logger = logging.getLogger(__name__)


async def bpjs_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handles /bpjs command.

    Triggers manual BPJS scan and sends alerts.

    Args:
        update: Telegram Update object
        context: Handler context
    """
    user = update.effective_user
    logger.info(f"/bpjs command from user {user.id} (@{user.username})")

    # Send scanning notification
    scanning_msg = await update.message.reply_text(
        format_scan_header("BPJS"),
        parse_mode="Markdown",
    )

    try:
        # Run the BPJS scan
        candidates = run_bpjs_scan(top_n=settings.TOP_N_RESULTS)

        # Delete scanning message
        await scanning_msg.delete()

        if not candidates:
            await update.message.reply_text(
                format_no_results("BPJS"),
                parse_mode="Markdown",
            )
            return

        # Send header
        await update.message.reply_text(
            f"🚀 *BPJS Scan Results* — {len(candidates)} kandidat ditemukan\n"
            f"━━━━━━━━━━━━━━━━━━",
            parse_mode="Markdown",
        )

        # Send each candidate as a separate alert
        for candidate in candidates:
            try:
                alert_text = format_bpjs_alert(candidate)
                await update.message.reply_text(
                    alert_text,
                    parse_mode="Markdown",
                )
            except Exception as e:
                logger.error(f"Error sending BPJS alert for {candidate.ticker}: {e}")

        # Send disclaimer footer
        await update.message.reply_text(
            format_disclaimer(),
            parse_mode="Markdown",
        )

    except Exception as e:
        logger.error(f"BPJS scan error: {e}", exc_info=True)
        await scanning_msg.delete()
        await update.message.reply_text(
            format_error(f"BPJS scan gagal: {str(e)[:100]}"),
            parse_mode="Markdown",
        )

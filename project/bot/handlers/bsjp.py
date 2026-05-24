"""
bot/handlers/bsjp.py
Handles the /bsjp command — manual BSJP scan trigger.

Runs the BSJP scanner and sends results to the user.
"""

import logging
from telegram import Update
from telegram.ext import ContextTypes

from screener.scanner import run_bsjp_scan
from bot.utils.formatter import (
    format_scan_header,
    format_bsjp_alert,
    format_no_results,
    format_error,
    format_disclaimer,
)
from config import settings

logger = logging.getLogger(__name__)


async def bsjp_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handles /bsjp command.

    Triggers manual BSJP scan and sends alerts.

    Args:
        update: Telegram Update object
        context: Handler context
    """
    user = update.effective_user
    logger.info(f"/bsjp command from user {user.id} (@{user.username})")

    # Send scanning notification
    scanning_msg = await update.message.reply_text(
        format_scan_header("BSJP"),
        parse_mode="Markdown",
    )

    try:
        # Run the BSJP scan
        candidates = run_bsjp_scan(top_n=settings.TOP_N_RESULTS)

        # Delete scanning message
        await scanning_msg.delete()

        if not candidates:
            await update.message.reply_text(
                format_no_results("BSJP"),
                parse_mode="Markdown",
            )
            return

        # Send header
        await update.message.reply_text(
            f"🌙 *BSJP Scan Results* — {len(candidates)} kandidat ditemukan\n"
            f"━━━━━━━━━━━━━━━━━━",
            parse_mode="Markdown",
        )

        # Send each candidate as a separate alert
        for candidate in candidates:
            try:
                alert_text = format_bsjp_alert(candidate)
                await update.message.reply_text(
                    alert_text,
                    parse_mode="Markdown",
                )
            except Exception as e:
                logger.error(f"Error sending BSJP alert for {candidate.ticker}: {e}")

        # Send disclaimer footer
        await update.message.reply_text(
            format_disclaimer(),
            parse_mode="Markdown",
        )

    except Exception as e:
        logger.error(f"BSJP scan error: {e}", exc_info=True)
        await scanning_msg.delete()
        await update.message.reply_text(
            format_error(f"BSJP scan gagal: {str(e)[:100]}"),
            parse_mode="Markdown",
        )

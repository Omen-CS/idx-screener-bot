"""
bot/handlers/top.py
Handles the /top command — shows top ranked candidates from both modes.

Provides a compact ranked list view without full alert detail.
"""

import logging
from telegram import Update
from telegram.ext import ContextTypes

from screener.scanner import run_bpjs_scan, run_bsjp_scan
from bot.utils.formatter import format_top_list, format_error
from config import settings

logger = logging.getLogger(__name__)


async def top_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handles /top command.

    Shows ranked top candidates from BPJS and BSJP scans in compact format.

    Args:
        update: Telegram Update object
        context: Handler context
    """
    user = update.effective_user
    logger.info(f"/top command from user {user.id} (@{user.username})")

    # Notify user
    scanning_msg = await update.message.reply_text(
        "🏆 *Fetching top candidates...*\nPlease wait.",
        parse_mode="Markdown",
    )

    try:
        # Run both scans with top 10 limit
        bpjs_candidates = run_bpjs_scan(top_n=settings.TOP_N_RESULTS)
        bsjp_candidates = run_bsjp_scan(top_n=settings.TOP_N_RESULTS)

        # Delete scanning message
        await scanning_msg.delete()

        # Send BPJS top list
        bpjs_message = format_top_list(bpjs_candidates, "BPJS")
        await update.message.reply_text(
            bpjs_message,
            parse_mode="Markdown",
        )

        # Send BSJP top list
        bsjp_message = format_top_list(bsjp_candidates, "BSJP")
        await update.message.reply_text(
            bsjp_message,
            parse_mode="Markdown",
        )

    except Exception as e:
        logger.error(f"Top command error: {e}", exc_info=True)
        try:
            await scanning_msg.delete()
        except Exception:
            pass
        await update.message.reply_text(
            format_error(f"Error fetching top candidates: {str(e)[:100]}"),
            parse_mode="Markdown",
        )

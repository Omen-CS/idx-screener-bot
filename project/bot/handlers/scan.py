"""
bot/handlers/scan.py
Handles the /scan command — runs both BPJS and BSJP scans.

Provides a combined view of both scanner modes.
"""

import logging
from telegram import Update
from telegram.ext import ContextTypes

from screener.scanner import run_full_scan
from bot.utils.formatter import (
    format_alert,
    format_no_results,
    format_error,
    format_disclaimer,
)
from config import settings

logger = logging.getLogger(__name__)


async def scan_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handles /scan command.

    Runs both BPJS and BSJP scans and sends combined results.

    Args:
        update: Telegram Update object
        context: Handler context
    """
    user = update.effective_user
    logger.info(f"/scan command from user {user.id} (@{user.username})")

    # Send initial scanning message
    scanning_msg = await update.message.reply_text(
        "🔍 *Running full scan (BPJS + BSJP)...*\n"
        "This will take 2-4 minutes. Please wait.",
        parse_mode="Markdown",
    )

    try:
        # Run both scans
        results = run_full_scan(top_n=5)  # Limit to top 5 per mode for /scan

        bpjs_candidates = results.get("bpjs", [])
        bsjp_candidates = results.get("bsjp", [])

        # Delete scanning message
        await scanning_msg.delete()

        total = len(bpjs_candidates) + len(bsjp_candidates)

        if total == 0:
            await update.message.reply_text(
                "📭 *No candidates found in either scan.*\n\n"
                "Market conditions don't show qualifying setups right now.\n"
                "Try during active trading hours (09:00 - 15:50 WIB).",
                parse_mode="Markdown",
            )
            return

        # Send summary header
        await update.message.reply_text(
            f"📊 *Full Scan Complete*\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🚀 BPJS: {len(bpjs_candidates)} kandidat\n"
            f"🌙 BSJP: {len(bsjp_candidates)} kandidat\n"
            f"━━━━━━━━━━━━━━━━━━",
            parse_mode="Markdown",
        )

        # Send BPJS results
        if bpjs_candidates:
            await update.message.reply_text(
                "🚀 *BPJS Candidates:*",
                parse_mode="Markdown",
            )
            for candidate in bpjs_candidates:
                try:
                    await update.message.reply_text(
                        format_alert(candidate),
                        parse_mode="Markdown",
                    )
                except Exception as e:
                    logger.error(f"Error sending alert for {candidate.ticker}: {e}")
        else:
            await update.message.reply_text(
                format_no_results("BPJS"),
                parse_mode="Markdown",
            )

        # Send BSJP results
        if bsjp_candidates:
            await update.message.reply_text(
                "🌙 *BSJP Candidates:*",
                parse_mode="Markdown",
            )
            for candidate in bsjp_candidates:
                try:
                    await update.message.reply_text(
                        format_alert(candidate),
                        parse_mode="Markdown",
                    )
                except Exception as e:
                    logger.error(f"Error sending alert for {candidate.ticker}: {e}")
        else:
            await update.message.reply_text(
                format_no_results("BSJP"),
                parse_mode="Markdown",
            )

        # Disclaimer
        await update.message.reply_text(
            format_disclaimer(),
            parse_mode="Markdown",
        )

    except Exception as e:
        logger.error(f"Full scan error: {e}", exc_info=True)
        try:
            await scanning_msg.delete()
        except Exception:
            pass
        await update.message.reply_text(
            format_error(f"Scan gagal: {str(e)[:100]}"),
            parse_mode="Markdown",
        )

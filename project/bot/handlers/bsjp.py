"""
bot/handlers/bsjp.py
"""
import logging
from telegram import Update
from telegram.ext import ContextTypes

from screener.scanner import run_bsjp_scan
from screener.tickers import get_idx_tickers
from bot.utils.formatter import (
    format_scan_header, format_bsjp_alert,
    format_no_results, format_error,
    format_scan_summary,
)
from config import settings

logger = logging.getLogger(__name__)


async def bsjp_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    logger.info(f"/bsjp from user {user.id} (@{user.username})")

    scanning_msg = await update.message.reply_text(
        format_scan_header("BSJP"), parse_mode="Markdown"
    )

    try:
        total_tickers = len(get_idx_tickers())
        candidates = run_bsjp_scan(top_n=settings.TOP_N_RESULTS)
        await scanning_msg.delete()

        if not candidates:
            await update.message.reply_text(
                format_no_results("BSJP"), parse_mode="Markdown"
            )
            return

        await update.message.reply_text(
            f"🌙 *BSJP Scan Results — {len(candidates)} kandidat ditemukan*\n"
            f"━━━━━━━━━━━━━━━━━━",
            parse_mode="Markdown",
        )

        for candidate in candidates:
            try:
                await update.message.reply_text(
                    format_bsjp_alert(candidate), parse_mode="Markdown"
                )
            except Exception as e:
                logger.error(f"Error sending alert {candidate.ticker}: {e}")

        # Ringkasan di akhir
        summary = format_scan_summary([], candidates, total_scanned=total_tickers)
        if summary:
            await update.message.reply_text(summary, parse_mode="Markdown")

    except Exception as e:
        logger.error(f"BSJP error: {e}", exc_info=True)
        try:
            await scanning_msg.delete()
        except Exception:
            pass
        await update.message.reply_text(
            format_error(str(e)[:100]), parse_mode="Markdown"
        )

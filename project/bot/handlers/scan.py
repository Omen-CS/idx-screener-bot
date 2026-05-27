"""
bot/handlers/scan.py
"""
import logging
from telegram import Update
from telegram.ext import ContextTypes

from screener.scanner import run_full_scan, market_status_msg, is_market_open
from screener.tickers import get_idx_tickers
from bot.utils.formatter import (
    format_alert, format_no_results, format_error,
    format_scan_summary,
)
from config import settings

logger = logging.getLogger(__name__)


async def scan_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    logger.info(f"/scan from user {user.id} (@{user.username})")

    market_note = "" if is_market_open() else "\n⚠️ _Market tutup — data sesi terakhir_"

    scanning_msg = await update.message.reply_text(
        f"🔍 *Running full scan (BPJS + BSJP)...*\n"
        f"📊 {market_status_msg()}\n"
        f"Mohon tunggu 1-3 menit.{market_note}",
        parse_mode="Markdown",
    )

    try:
        total_tickers    = len(get_idx_tickers())
        results          = run_full_scan(top_n=settings.TOP_N_RESULTS)
        bpjs_candidates  = results.get("bpjs", [])
        bsjp_candidates  = results.get("bsjp", [])

        await scanning_msg.delete()

        total = len(bpjs_candidates) + len(bsjp_candidates)

        if total == 0:
            await update.message.reply_text(
                f"📭 *Tidak ada kandidat ditemukan*\n\n"
                f"📊 {market_status_msg()}{market_note}",
                parse_mode="Markdown",
            )
            return

        await update.message.reply_text(
            f"📊 *Full Scan Complete*\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🚀 BPJS: {len(bpjs_candidates)} kandidat\n"
            f"🌙 BSJP: {len(bsjp_candidates)} kandidat\n"
            f"📡 {market_status_msg()}{market_note}\n"
            f"━━━━━━━━━━━━━━━━━━",
            parse_mode="Markdown",
        )

        if bpjs_candidates:
            await update.message.reply_text("🚀 *BPJS Candidates:*", parse_mode="Markdown")
            for c in bpjs_candidates:
                try:
                    await update.message.reply_text(format_alert(c), parse_mode="Markdown")
                except Exception as e:
                    logger.error(f"Alert error {c.ticker}: {e}")
        else:
            await update.message.reply_text(format_no_results("BPJS"), parse_mode="Markdown")

        if bsjp_candidates:
            await update.message.reply_text("🌙 *BSJP Candidates:*", parse_mode="Markdown")
            for c in bsjp_candidates:
                try:
                    await update.message.reply_text(format_alert(c), parse_mode="Markdown")
                except Exception as e:
                    logger.error(f"Alert error {c.ticker}: {e}")
        else:
            await update.message.reply_text(format_no_results("BSJP"), parse_mode="Markdown")

        # Ringkasan di akhir
        summary = format_scan_summary(
            bpjs_candidates, bsjp_candidates, total_scanned=total_tickers
        )
        if summary:
            await update.message.reply_text(summary, parse_mode="Markdown")

    except Exception as e:
        logger.error(f"Scan error: {e}", exc_info=True)
        try:
            await scanning_msg.delete()
        except Exception:
            pass
        await update.message.reply_text(
            format_error(str(e)[:100]), parse_mode="Markdown"
        )

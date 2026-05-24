"""
bot/handlers/top.py
Handles the /top command — shows top ranked candidates from both modes.
"""

import asyncio
import logging
from telegram import Update
from telegram.ext import ContextTypes

# Ganti import ke fungsi gabungan yang baru
from screener.scanner import run_combined_top_scan
from bot.utils.formatter import format_top_list, format_error
from config import settings

logger = logging.getLogger(__name__)


async def top_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    logger.info(f"/top command from user {user.id} (@{user.username})")

    scanning_msg = await update.message.reply_text(
        "🏆 *Fetching top candidates...*\nMohon tunggu, sedang memproses 218 saham IDX.",
        parse_mode="Markdown",
    )

    try:
        # Jalankan kalkulasi sinkronus di dalam thread terpisah agar bot tidak hang/freeze
        bpjs_candidates, bsjp_candidates = await asyncio.to_thread(
            run_combined_top_scan, 
            top_n=settings.TOP_N_RESULTS
        )

        # Hapus pesan "Please wait"
        await scanning_msg.delete()

        # Kirim hasil BPJS
        bpjs_message = format_top_list(bpjs_candidates, "BPJS")
        await update.message.reply_text(bpjs_message, parse_mode="Markdown")

        # Kirim hasil BSJP
        bsjp_message = format_top_list(bsjp_candidates, "BSJP")
        await update.message.reply_text(bsjp_message, parse_mode="Markdown")

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

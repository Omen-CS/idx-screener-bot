"""
bot/handlers/start.py
Handles the /start command.

Sends a welcome message with bot description and available commands.
"""

import logging
from telegram import Update
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

WELCOME_MESSAGE = """
👋 *Selamat datang di IDX Momentum Screener Bot!*

Bot ini secara otomatis memindai saham Indonesia (IDX) dan mengirim sinyal momentum.

━━━━━━━━━━━━━━━━━━
📋 *Perintah yang tersedia:*

🚀 `/bpjs` — Scan BPJS manual
_(Beli Pagi Jual Sore — intraday momentum)_

🌙 `/bsjp` — Scan BSJP manual
_(Beli Sore Jual Pagi — overnight continuation)_

📊 `/scan` — Jalankan kedua scan sekarang

🏆 `/top` — Tampilkan kandidat terbaik

━━━━━━━━━━━━━━━━━━
⏰ *Jadwal scan otomatis:*
• 09:00 WIB → BPJS Scan
• 14:00 WIB → BSJP Scan

━━━━━━━━━━━━━━━━━━
⚠️ _Bukan saran keuangan. Selalu lakukan riset sendiri. Trading mengandung risiko._
"""


async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handles /start command.

    Args:
        update: Telegram Update object
        context: Handler context
    """
    user = update.effective_user
    logger.info(f"/start command from user {user.id} (@{user.username})")

    await update.message.reply_text(
        WELCOME_MESSAGE,
        parse_mode="Markdown",
    )

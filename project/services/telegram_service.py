"""
services/telegram_service.py
Service for sending Telegram messages programmatically.

Used by the scheduler to send automatic alerts without user interaction.
Separate from the bot handlers which handle user commands.
"""

import logging
import asyncio
from typing import List, Optional

from telegram import Bot
from telegram.error import TelegramError

from config import settings
from screener.scanner import StockCandidate
from bot.utils.formatter import format_bpjs_alert, format_bsjp_alert, format_disclaimer

logger = logging.getLogger(__name__)


async def send_message(text: str, chat_id: str = None) -> bool:
    """
    Sends a text message to the configured Telegram chat.

    Args:
        text: Message text (supports Markdown)
        chat_id: Override chat ID (defaults to settings.TELEGRAM_CHAT_ID)

    Returns:
        bool: True if message sent successfully
    """
    target_chat = chat_id or settings.TELEGRAM_CHAT_ID

    if not target_chat:
        logger.error("No TELEGRAM_CHAT_ID configured. Cannot send message.")
        return False

    if not settings.TELEGRAM_BOT_TOKEN:
        logger.error("No TELEGRAM_BOT_TOKEN configured. Cannot send message.")
        return False

    try:
        bot = Bot(token=settings.TELEGRAM_BOT_TOKEN)
        await bot.send_message(
            chat_id=target_chat,
            text=text,
            parse_mode="Markdown",
        )
        return True
    except TelegramError as e:
        logger.error(f"Telegram API error sending message: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error sending Telegram message: {e}")
        return False


async def send_bpjs_alerts(candidates: List[StockCandidate]) -> None:
    """
    Sends BPJS alerts to the configured chat.
    Called automatically by the scheduler at 09:00 WIB.

    Args:
        candidates: List of BPJS candidates from the scanner
    """
    if not candidates:
        await send_message(
            "🚀 *BPJS Auto Scan (09:00 WIB)*\n\n"
            "📭 Tidak ada kandidat yang memenuhi syarat saat ini.\n"
            "Market conditions tidak menunjukkan setup yang valid."
        )
        return

    # Send header
    await send_message(
        f"🚀 *BPJS Auto Scan — 09:00 WIB*\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"Ditemukan *{len(candidates)}* kandidat momentum intraday."
    )

    # Send each alert
    for candidate in candidates:
        try:
            alert_text = format_bpjs_alert(candidate)
            success = await send_message(alert_text)
            if not success:
                logger.warning(f"Failed to send BPJS alert for {candidate.ticker}")
            # Small delay to avoid flood limits
            await asyncio.sleep(0.5)
        except Exception as e:
            logger.error(f"Error sending BPJS alert for {candidate.ticker}: {e}")

    # Send disclaimer
    await send_message(format_disclaimer())


async def send_bsjp_alerts(candidates: List[StockCandidate]) -> None:
    """
    Sends BSJP alerts to the configured chat.
    Called automatically by the scheduler at 14:00 WIB.

    Args:
        candidates: List of BSJP candidates from the scanner
    """
    if not candidates:
        await send_message(
            "🌙 *BSJP Auto Scan (14:00 WIB)*\n\n"
            "📭 Tidak ada kandidat yang memenuhi syarat saat ini.\n"
            "Market conditions tidak menunjukkan setup yang valid."
        )
        return

    # Send header
    await send_message(
        f"🌙 *BSJP Auto Scan — 14:00 WIB*\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"Ditemukan *{len(candidates)}* kandidat overnight continuation."
    )

    # Send each alert
    for candidate in candidates:
        try:
            alert_text = format_bsjp_alert(candidate)
            success = await send_message(alert_text)
            if not success:
                logger.warning(f"Failed to send BSJP alert for {candidate.ticker}")
            await asyncio.sleep(0.5)
        except Exception as e:
            logger.error(f"Error sending BSJP alert for {candidate.ticker}: {e}")

    # Send disclaimer
    await send_message(format_disclaimer())


def send_message_sync(text: str, chat_id: str = None) -> bool:
    """
    Synchronous wrapper for send_message.
    Used when calling from non-async contexts (like APScheduler jobs).

    Args:
        text: Message to send
        chat_id: Optional chat ID override

    Returns:
        bool: True if successful
    """
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(send_message(text, chat_id))
        loop.close()
        return result
    except Exception as e:
        logger.error(f"sync send_message error: {e}")
        return False

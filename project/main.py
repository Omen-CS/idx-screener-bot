"""
main.py
Entry point for the IDX Momentum Screener Bot.

Responsibilities:
1. Configure logging
2. Validate environment variables
3. Start APScheduler for automatic scans
4. Start the Telegram bot with all command handlers
5. Handle graceful shutdown
"""

import asyncio
import logging
import os
import sys
from pathlib import Path

# ===========================================================================
# FIX ABSOLUT JALUR RAILWAY (Menembak langsung ke root eksekusi bot)
# ===========================================================================
root_dir = Path(__file__).resolve().parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from telegram import Update
from telegram.ext import Application, CommandHandler

# ---------------------------------------------------------------------------
# Logging configuration — must be set up BEFORE any other imports
# ---------------------------------------------------------------------------
def setup_logging() -> None:
    """Configure console and file logging."""
    from config.settings import LOG_LEVEL, LOG_FILE

    # Ensure logs directory exists
    Path("logs").mkdir(exist_ok=True)

    log_format = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"

    # Determine numeric log level
    numeric_level = getattr(logging, LOG_LEVEL.upper(), logging.INFO)

    # Root logger configuration
    logging.basicConfig(
        level=numeric_level,
        format=log_format,
        datefmt=date_format,
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(LOG_FILE, encoding="utf-8"),
        ],
    )

    # Suppress noisy third-party loggers
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("telegram").setLevel(logging.WARNING)
    logging.getLogger("apscheduler").setLevel(logging.INFO)
    logging.getLogger("yfinance").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)


# Set up logging immediately
setup_logging()

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Import project modules AFTER logging is configured
# ---------------------------------------------------------------------------
from config import settings
from bot.handlers.start import start_handler
from bot.handlers.scan import scan_handler
from bot.handlers.bpjs import bpjs_handler
from bot.handlers.bsjp import bsjp_handler
from bot.handlers.top import top_handler
from services.scheduler_service import create_scheduler


def validate_config() -> bool:
    """
    Validates that required environment variables are set.

    Returns:
        bool: True if all required config is present
    """
    missing = []

    if not settings.TELEGRAM_BOT_TOKEN:
        missing.append("TELEGRAM_BOT_TOKEN")

    if not settings.TELEGRAM_CHAT_ID:
        missing.append("TELEGRAM_CHAT_ID")

    if missing:
        logger.error(
            f"Missing required environment variables: {', '.join(missing)}\n"
            f"Please set these in your .env file or Railway environment variables."
        )
        return False

    return True


def create_application() -> Application:
    """
    Creates and configures the Telegram bot application.

    Registers all command handlers.

    Returns:
        Application: Configured telegram bot application
    """
    app = Application.builder().token(settings.TELEGRAM_BOT_TOKEN).build()

    # Register command handlers
    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(CommandHandler("scan", scan_handler))
    app.add_handler(CommandHandler("bpjs", bpjs_handler))
    app.add_handler(CommandHandler("bsjp", bsjp_handler))
    app.add_handler(CommandHandler("top", top_handler))

    logger.info("Telegram bot application configured with all handlers")
    return app


# ---------------------------------------------------------------------------
# Main Routine — Diubah menggunakan pendekatan run_polling synchronous wrapper
# ---------------------------------------------------------------------------
def main() -> None:
    """
    Main entry point.
    Starts both the scheduler and the Telegram bot polling loop safely.
    """
    logger.info("=" * 60)
    logger.info("IDX Momentum Screener Bot — Starting up")
    logger.info("=" * 60)

    # Validate config before proceeding
    if not validate_config():
        logger.critical("Configuration validation failed. Exiting.")
        sys.exit(1)

    logger.info(f"Bot Token: {settings.TELEGRAM_BOT_TOKEN[:10]}...")
    logger.info(f"Chat ID: {settings.TELEGRAM_CHAT_ID}")

    # Create scheduler
    scheduler = create_scheduler()

    # Create Telegram application
    app = create_application()

    # Start scheduler
    scheduler.start()
    logger.info("APScheduler started")

    # Hook untuk mengirim pesan startup secara aman saat aplikasi menginisialisasi
    async def post_init(application: Application) -> None:
        try:
            from services.telegram_service import send_message
            await send_message(
                "🤖 *IDX Screener Bot Online*\n\n"
                "Bot berhasil dijalankan.\n\n"
                f"⏰ Jadwal scan otomatis:\n"
                f"• BPJS: {settings.BPJS_HOUR:02d}:{settings.BPJS_MINUTE:02d} WIB\n"
                f"• BSJP: {settings.BSJP_HOUR:02d}:{settings.BSJP_MINUTE:02d} WIB\n\n"
                f"Ketik /start untuk melihat perintah yang tersedia."
            )
            logger.info("Startup notification sent successfully.")
        except Exception as e:
            logger.warning(f"Could not send startup notification: {e}")

    # Daftarkan post_init ke dalam aplikasi telegram
    app.post_init = post_init

    # Start polling — let python-telegram-bot handle the event loop safely
    logger.info("Starting Telegram bot polling...")
    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,  # Skip messages received while bot was offline
    )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Bot stopped by user (KeyboardInterrupt)")
    except Exception as e:
        logger.critical(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)

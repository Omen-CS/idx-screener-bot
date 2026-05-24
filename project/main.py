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

import logging
import os
import sys
from pathlib import Path

# Hapus import Update jika tidak dipakai langsung di sini
from telegram.ext import Application, CommandHandler

# Skenario: Asumsi fungsi-fungsi ini di-import dari modul service/config kamu
from config.settings import LOG_LEVEL, LOG_FILE, TELEGRAM_BOT_TOKEN
from services.scheduler_service import configure_scheduler, scheduler
from handlers.command_handlers import start_command, scan_command # Contoh handler Anda

# ---------------------------------------------------------------------------
# Logging configuration
# ---------------------------------------------------------------------------
def setup_logging() -> None:
    """Configure console and file logging."""
    Path("logs").mkdir(exist_ok=True)

    log_format = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"

    numeric_level = getattr(logging, LOG_LEVEL.upper(), logging.INFO)
    
    logging.basicConfig(
        level=numeric_level,
        format=log_format,
        datefmt=date_format,
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(LOG_FILE, encoding="utf-8")
        ]
    )

# ---------------------------------------------------------------------------
# Main Routine
# ---------------------------------------------------------------------------
def main() -> None:
    """Main entry point using synchronous setup for run_polling."""
    # 1. Setup Logging
    setup_logging()
    logger = logging.getLogger(__name__)
    
    logger.info("=" * 60)
    logger.info("IDX Momentum Screener Bot — Starting up")
    logger.info("=" * 60)

    # 2. Validate Environment Variables
    if not TELEGRAM_BOT_TOKEN:
        logger.critical("TELEGRAM_BOT_TOKEN is missing! Exiting...")
        sys.exit(1)

    try:
        # 3. Start APScheduler
        # Pastikan scheduler menggunakan AsyncIOScheduler atau BackgroundScheduler.
        # Jika menggunakan AsyncIOScheduler, python-telegram-bot otomatis akan
        # membagikan event loop-nya ke scheduler saat bot mulai berjalan.
        configure_scheduler()
        scheduler.start()
        logger.info("APScheduler started successfully.")

        # 4. Configure Telegram Bot Application
        app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

        # Register your handlers here
        # app.add_handler(CommandHandler("start", start_command))
        # app.add_handler(CommandHandler("scan", scan_command))
        logger.info("Telegram bot application configured with all handlers.")

        # 5. Start Polling (BLOCKING)
        # Fungsi ini sinkron, akan membuat event loop baru sendiri secara aman,
        # dan otomatis menangani graceful shutdown (Ctrl+C) tanpa bikin error loop crash.
        logger.info("Starting Telegram bot polling...")
        app.run_polling()

    except Exception as e:
        logger.critical(f"Fatal error during runtime: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    # Panggil main() secara langsung tanpa asyncio.run()
    main()

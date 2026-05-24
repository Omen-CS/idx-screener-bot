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

# Memastikan root folder masuk ke dalam sys.path Python
base_dir = Path(__file__).resolve().parent
if str(base_dir) not in sys.path:
    sys.path.insert(0, str(base_dir))

from telegram.ext import Application, CommandHandler

# ---------------------------------------------------------------------------
# Import internal proyek Anda
# ---------------------------------------------------------------------------
from config import settings
from services.scheduler_service import create_scheduler

# PERBAIKAN IMPORT: Diambil langsung dari file start.py dan scan.py di folder handlers
from handlers.start import start_command
from handlers.scan import scan_command

# ---------------------------------------------------------------------------
# Logging configuration
# ---------------------------------------------------------------------------
def setup_logging() -> None:
    """Configure console and file logging."""
    Path("logs").mkdir(exist_ok=True)

    log_format = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"

    numeric_level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
    
    logging.basicConfig(
        level=numeric_level,
        format=log_format,
        datefmt=date_format,
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(settings.LOG_FILE, encoding="utf-8")
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
    if not settings.TELEGRAM_BOT_TOKEN:
        logger.critical("TELEGRAM_BOT_TOKEN missing dari settings! Exiting...")
        sys.exit(1)

    try:
        # 3. Initialize & Start APScheduler
        scheduler = create_scheduler()
        scheduler.start()
        logger.info("APScheduler started successfully and running in background.")

        # 4. Configure Telegram Bot Application
        app = Application.builder().token(settings.TELEGRAM_BOT_TOKEN).build()

        # Daftarkan handler-nya ke bot aplikasi menggunakan fungsi yang di-import
        app.add_handler(CommandHandler("start", start_command))
        app.add_handler(CommandHandler("scan", scan_command))
        
        logger.info("Telegram bot application configured with handlers (/start and /scan).")

        # 5. Start Polling (BLOCKING)
        logger.info("Starting Telegram bot polling...")
        app.run_polling()

    except Exception as e:
        logger.critical(f"Fatal error during runtime: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    main()

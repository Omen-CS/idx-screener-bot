"""
main.py
Entry point for the IDX Momentum Screener Bot.
"""

import logging
import sys
from pathlib import Path

# Fix path Railway
root_dir = Path(__file__).resolve().parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

# ---------------------------------------------------------------------------
# Logging — harus setup SEBELUM import lain
# ---------------------------------------------------------------------------
def setup_logging() -> None:
    from config.settings import LOG_LEVEL, LOG_FILE
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
            logging.FileHandler(LOG_FILE, encoding="utf-8"),
        ],
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("telegram").setLevel(logging.WARNING)
    logging.getLogger("apscheduler").setLevel(logging.INFO)
    logging.getLogger("yfinance").setLevel(logging.CRITICAL)  # suppress yfinance warnings
    logging.getLogger("urllib3").setLevel(logging.WARNING)


setup_logging()
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Import setelah logging setup
# ---------------------------------------------------------------------------
from telegram import Update
from telegram.ext import Application, CommandHandler

from config import settings
from bot.handlers.start import start_handler
from bot.handlers.scan import scan_handler
from bot.handlers.bpjs import bpjs_handler
from bot.handlers.bsjp import bsjp_handler
from bot.handlers.top import top_handler
from bot.handlers.debug import debug_handler


# ---------------------------------------------------------------------------
# Validate env vars
# ---------------------------------------------------------------------------
def validate_config() -> bool:
    missing = []
    if not settings.TELEGRAM_BOT_TOKEN:
        missing.append("TELEGRAM_BOT_TOKEN")
    if not settings.TELEGRAM_CHAT_ID:
        missing.append("TELEGRAM_CHAT_ID")
    if missing:
        logger.error(f"Missing env vars: {', '.join(missing)}")
        return False
    return True


# ---------------------------------------------------------------------------
# post_init — jalan INSIDE PTB event loop, tempat yang benar untuk start scheduler
# ---------------------------------------------------------------------------
async def post_init(application: Application) -> None:
    """
    Dipanggil PTB setelah Application fully initialized.
    Scheduler di-start di sini supaya pakai event loop yang sama dengan PTB.
    JANGAN start scheduler di luar (di main/synchronous scope) — itu yang
    nyebabin Conflict error dan double-scheduler.
    """
    from services.scheduler_service import create_scheduler
    scheduler = create_scheduler()
    scheduler.start()
    logger.info("APScheduler started inside PTB event loop")

    try:
        from services.telegram_service import send_message
        await send_message(
            "🤖 *IDX Screener Bot Online*\n\n"
            "Bot berhasil dijalankan.\n\n"
            f"⏰ Jadwal scan otomatis:\n"
            f"• BPJS: {settings.BPJS_HOUR:02d}:{settings.BPJS_MINUTE:02d} WIB\n"
            f"• BSJP: {settings.BSJP_HOUR:02d}:{settings.BSJP_MINUTE:02d} WIB\n\n"
            "Ketik /start untuk melihat perintah yang tersedia."
        )
        logger.info("Startup notification sent successfully.")
    except Exception as e:
        logger.warning(f"Could not send startup notification: {e}")


# ---------------------------------------------------------------------------
# Build Application
# ---------------------------------------------------------------------------
def create_application() -> Application:
    # post_init di-pass lewat .builder() — BUKAN assign langsung ke app.post_init
    app = (
        Application.builder()
        .token(settings.TELEGRAM_BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(CommandHandler("scan", scan_handler))
    app.add_handler(CommandHandler("bpjs", bpjs_handler))
    app.add_handler(CommandHandler("bsjp", bsjp_handler))
    app.add_handler(CommandHandler("top", top_handler))
    app.add_handler(CommandHandler("debug", debug_handler))  # tambah balik debug

    logger.info("Handlers registered: start, scan, bpjs, bsjp, top, debug")
    return app


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main() -> None:
    logger.info("=" * 60)
    logger.info("IDX Momentum Screener Bot — Starting up")
    logger.info("=" * 60)

    if not validate_config():
        logger.critical("Config validation failed. Exiting.")
        sys.exit(1)

    logger.info(f"Bot Token: {settings.TELEGRAM_BOT_TOKEN[:10]}...")
    logger.info(f"Chat ID:   {settings.TELEGRAM_CHAT_ID}")

    app = create_application()

    logger.info("Starting Telegram bot polling...")
    # run_polling() adalah synchronous call — dia manage event loop-nya sendiri
    # JANGAN wrap dengan asyncio.run() dan JANGAN start scheduler sebelum ini
    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
    )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Bot stopped by user (KeyboardInterrupt)")
    except Exception as e:
        logger.critical(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)

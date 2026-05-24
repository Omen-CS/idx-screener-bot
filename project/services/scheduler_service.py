"""
services/scheduler_service.py
APScheduler configuration for automatic scan jobs.

Jobs:
- 09:00 WIB → BPJS scan + Telegram alerts
- 14:00 WIB → BSJP scan + Telegram alerts

Uses asyncio-compatible scheduler to work with python-telegram-bot v20+.
"""

import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from config import settings
from screener.scanner import run_bpjs_scan, run_bsjp_scan
from services.telegram_service import send_bpjs_alerts, send_bsjp_alerts

logger = logging.getLogger(__name__)


async def run_bpjs_job() -> None:
    """
    Scheduled BPJS job — runs at 09:00 WIB every weekday.

    Executes the BPJS scanner and sends results via Telegram.
    """
    logger.info("⏰ Scheduled BPJS job triggered")

    try:
        candidates = run_bpjs_scan(top_n=settings.TOP_N_RESULTS)
        logger.info(f"BPJS scan found {len(candidates)} candidates")
        await send_bpjs_alerts(candidates)
        logger.info("BPJS alerts sent successfully")
    except Exception as e:
        logger.error(f"BPJS scheduled job error: {e}", exc_info=True)
        # Attempt to send error notification
        try:
            from services.telegram_service import send_message
            await send_message(
                f"⚠️ *BPJS Auto Scan Error*\n\n"
                f"Scan gagal: {str(e)[:200]}\n"
                f"Periksa logs untuk detail."
            )
        except Exception:
            pass


async def run_bsjp_job() -> None:
    """
    Scheduled BSJP job — runs at 14:00 WIB every weekday.

    Executes the BSJP scanner and sends results via Telegram.
    """
    logger.info("⏰ Scheduled BSJP job triggered")

    try:
        candidates = run_bsjp_scan(top_n=settings.TOP_N_RESULTS)
        logger.info(f"BSJP scan found {len(candidates)} candidates")
        await send_bsjp_alerts(candidates)
        logger.info("BSJP alerts sent successfully")
    except Exception as e:
        logger.error(f"BSJP scheduled job error: {e}", exc_info=True)
        try:
            from services.telegram_service import send_message
            await send_message(
                f"⚠️ *BSJP Auto Scan Error*\n\n"
                f"Scan gagal: {str(e)[:200]}\n"
                f"Periksa logs untuk detail."
            )
        except Exception:
            pass


def create_scheduler() -> AsyncIOScheduler:
    """
    Creates and configures the APScheduler instance.

    Returns AsyncIOScheduler with BPJS and BSJP jobs registered.
    Both jobs run Monday-Friday only (Indonesian market days).

    Returns:
        AsyncIOScheduler: Configured scheduler (not yet started)
    """
    scheduler = AsyncIOScheduler(timezone=settings.WIB)

    # BPJS Job — 09:00 WIB, Monday to Friday
    scheduler.add_job(
        run_bpjs_job,
        trigger=CronTrigger(
            hour=settings.BPJS_HOUR,
            minute=settings.BPJS_MINUTE,
            day_of_week="mon-fri",
            timezone=settings.WIB,
        ),
        id="bpjs_scan",
        name="BPJS Morning Scan",
        replace_existing=True,
        misfire_grace_time=300,  # Allow 5 min late start
    )

    # BSJP Job — 14:00 WIB, Monday to Friday
    scheduler.add_job(
        run_bsjp_job,
        trigger=CronTrigger(
            hour=settings.BSJP_HOUR,
            minute=settings.BSJP_MINUTE,
            day_of_week="mon-fri",
            timezone=settings.WIB,
        ),
        id="bsjp_scan",
        name="BSJP Afternoon Scan",
        replace_existing=True,
        misfire_grace_time=300,
    )

    logger.info(
        f"Scheduler configured: "
        f"BPJS at {settings.BPJS_HOUR:02d}:{settings.BPJS_MINUTE:02d} WIB, "
        f"BSJP at {settings.BSJP_HOUR:02d}:{settings.BSJP_MINUTE:02d} WIB"
    )

    return scheduler

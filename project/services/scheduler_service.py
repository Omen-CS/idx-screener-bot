"""
services/scheduler_service.py

BPJS: 09:30 WIB (bukan 09:00)
Alasan: jam 09:00-09:30 data 5m baru 6-12 bar, terlalu sedikit untuk
        kalkulasi VWAP, projected volume, dan higher low yang akurat.
        Jam 09:30 sudah ~18 bar — lebih stabil dan representatif.

BSJP: tetap 14:00 WIB
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
    logger.info("⏰ BPJS job triggered (09:30 WIB)")
    try:
        candidates = run_bpjs_scan(top_n=settings.TOP_N_RESULTS)
        logger.info(f"BPJS: {len(candidates)} kandidat")
        await send_bpjs_alerts(candidates)
    except Exception as e:
        logger.error(f"BPJS job error: {e}", exc_info=True)
        try:
            from services.telegram_service import send_message
            await send_message(f"⚠️ *BPJS Scan Error*\n{str(e)[:200]}")
        except Exception:
            pass


async def run_bsjp_job() -> None:
    logger.info("⏰ BSJP job triggered (14:00 WIB)")
    try:
        candidates = run_bsjp_scan(top_n=settings.TOP_N_RESULTS)
        logger.info(f"BSJP: {len(candidates)} kandidat")
        await send_bsjp_alerts(candidates)
    except Exception as e:
        logger.error(f"BSJP job error: {e}", exc_info=True)
        try:
            from services.telegram_service import send_message
            await send_message(f"⚠️ *BSJP Scan Error*\n{str(e)[:200]}")
        except Exception:
            pass


def create_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=settings.WIB)

    # BPJS: 09:30 WIB — data sudah ~18 bar 5m, lebih stabil
    scheduler.add_job(
        run_bpjs_job,
        trigger=CronTrigger(
            hour=9, minute=30,
            day_of_week="mon-fri",
            timezone=settings.WIB,
        ),
        id="bpjs_scan",
        name="BPJS Morning Scan",
        replace_existing=True,
        misfire_grace_time=300,
    )

    # BSJP: 14:00 WIB
    scheduler.add_job(
        run_bsjp_job,
        trigger=CronTrigger(
            hour=14, minute=0,
            day_of_week="mon-fri",
            timezone=settings.WIB,
        ),
        id="bsjp_scan",
        name="BSJP Afternoon Scan",
        replace_existing=True,
        misfire_grace_time=300,
    )

    logger.info("Scheduler: BPJS 09:30 WIB | BSJP 14:00 WIB")
    return scheduler

"""
bot/handlers/debug.py
/debug — test berbagai format URL Stooq + network check
"""

import logging
import requests
from io import StringIO
from telegram import Update
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}


def _test_stooq_formats() -> str:
    """Test semua kemungkinan format URL Stooq untuk IDX."""
    import pandas as pd

    formats = [
        ("bbca.id",   f"https://stooq.com/q/d/l/?s=bbca.id&i=d"),
        ("BBCA.ID",   f"https://stooq.com/q/d/l/?s=BBCA.ID&i=d"),
        ("bbca.jk",   f"https://stooq.com/q/d/l/?s=bbca.jk&i=d"),
        ("BBCA.JK",   f"https://stooq.com/q/d/l/?s=BBCA.JK&i=d"),
        ("bbca",      f"https://stooq.com/q/d/l/?s=bbca&i=d"),
        ("bbca.id+date", f"https://stooq.com/q/d/l/?s=bbca.id&i=d&d1=20250101&d2=20260526"),
    ]

    lines = ["🔍 *Stooq Format Test (BBCA)*", "━━━━━━━━━━━━━━━━━━"]
    for label, url in formats:
        try:
            r = requests.get(url, headers=HEADERS, timeout=6)
            text = r.text.strip()
            has_date = "Date" in text
            has_open = "Open" in text
            lines.append(
                f"`{label}`: HTTP {r.status_code} | "
                f"len={len(text)} | "
                f"CSV={'✅' if (has_date and has_open) else '❌'} | "
                f"preview: `{text[:40]}`"
            )
        except Exception as e:
            lines.append(f"`{label}`: ❌ {str(e)[:40]}")

    return "\n".join(lines)


def _test_network() -> str:
    lines = []
    tests = [
        ("Yahoo Finance", "https://query1.finance.yahoo.com/v8/finance/chart/BBCA.JK?interval=1d&range=5d"),
        ("Stooq",         "https://stooq.com/q/d/l/?s=bbca.id&i=d"),
        ("Google",        "https://www.google.com"),
        ("Alpha Vantage", "https://www.alphavantage.co"),
    ]
    for name, url in tests:
        try:
            r = requests.get(url, headers=HEADERS, timeout=5)
            lines.append(f"{'✅' if r.status_code == 200 else '⚠️'} {name}: HTTP {r.status_code}")
        except Exception as e:
            lines.append(f"❌ {name}: {str(e)[:50]}")
    return "\n".join(lines)


async def debug_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    logger.info(f"/debug from user {user.id} (@{user.username})")

    arg = context.args[0].lower() if context.args else ""

    # /debug network
    if arg == "network":
        msg = await update.message.reply_text("🌐 Testing network...")
        result = _test_network()
        await msg.delete()
        await update.message.reply_text(
            f"🌐 *Network Test*\n━━━━━━━━━━━━━━━━━━\n{result}\n━━━━━━━━━━━━━━━━━━",
            parse_mode="Markdown",
        )
        return

    # /debug stooq — test semua format URL
    if arg == "stooq":
        msg = await update.message.reply_text("🔍 Testing semua format Stooq...")
        result = _test_stooq_formats()
        await msg.delete()
        await update.message.reply_text(result, parse_mode="Markdown")
        return

    # /debug atau /debug BBCA — test fetch via market_data
    if context.args and arg not in ("network", "stooq"):
        ticker = context.args[0].upper().strip()
        if not ticker.endswith(".JK"):
            ticker += ".JK"
        tickers = [ticker]
    else:
        tickers = ["BBCA.JK", "BBRI.JK", "ANTM.JK"]

    msg = await update.message.reply_text(f"🔧 Testing {len(tickers)} ticker...")

    from services.market_data import fetch_daily, clear_cache
    clear_cache()

    lines = ["🔧 *Debug: Data Test*", "━━━━━━━━━━━━━━━━━━"]
    for ticker in tickers:
        try:
            df = fetch_daily(ticker)
            if df is None or df.empty:
                lines.append(f"\n*{ticker.replace('.JK','')}*: ❌ kosong")
            else:
                close = df["Close"].iloc[-1]
                date = str(df.index[-1])[:10]
                lines.append(f"\n*{ticker.replace('.JK','')}*: ✅ {len(df)} bars | {date} | close={close:,.0f}")
        except Exception as e:
            lines.append(f"\n*{ticker.replace('.JK','')}*: ❌ {str(e)[:60]}")

    lines.append("\n━━━━━━━━━━━━━━━━━━")
    lines.append("_/debug stooq → test format URL | /debug network → test koneksi_")

    await msg.delete()
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

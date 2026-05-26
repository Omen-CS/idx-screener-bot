"""
bot/handlers/debug.py
/debug — test koneksi + fetch data langsung dari Stooq
"""

import logging
import requests
from io import StringIO
from telegram import Update
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

DEFAULT_TICKERS = ["BBCA.JK", "BBRI.JK", "ANTM.JK", "TLKM.JK", "GOTO.JK"]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}


def _fetch_stooq_direct(ticker: str) -> str:
    """Fetch satu ticker langsung dari Stooq, return status string."""
    import pandas as pd
    symbol = ticker.replace(".JK", "").lower()
    url = f"https://stooq.com/q/d/l/?s={symbol}.id&i=d"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=6)
        if resp.status_code != 200:
            return f"❌ HTTP {resp.status_code}"
        text = resp.text.strip()
        if "Date" not in text or len(text) < 50:
            return f"❌ Response kosong (len={len(text)})"
        df = pd.read_csv(StringIO(text))
        if df.empty:
            return "❌ DataFrame kosong"
        close = df["Close"].iloc[-1]
        date = df["Date"].iloc[-1]
        return f"✅ {len(df)} bars | last={date} close={close:,.0f}"
    except Exception as e:
        return f"❌ Error: {str(e)[:60]}"


def _test_network() -> str:
    lines = []
    # Yahoo Finance
    try:
        r = requests.get(
            "https://query1.finance.yahoo.com/v8/finance/chart/BBCA.JK?interval=1d&range=5d",
            timeout=5
        )
        lines.append(f"{'✅' if r.status_code == 200 else '⚠️'} Yahoo Finance: HTTP {r.status_code}")
    except Exception as e:
        lines.append(f"❌ Yahoo Finance: {str(e)[:50]}")

    # Stooq
    try:
        r = requests.get(
            "https://stooq.com/q/d/l/?s=bbca.id&i=d",
            headers=HEADERS, timeout=5
        )
        if r.status_code == 200 and "Date" in r.text:
            lines.append(f"✅ Stooq: HTTP 200 + data OK")
        else:
            lines.append(f"⚠️ Stooq: HTTP {r.status_code} (data={len(r.text)} chars)")
    except Exception as e:
        lines.append(f"❌ Stooq: {str(e)[:50]}")

    # Google baseline
    try:
        r = requests.get("https://www.google.com", timeout=5)
        lines.append(f"✅ Google: HTTP {r.status_code}")
    except Exception as e:
        lines.append(f"❌ Google: {str(e)[:50]}")

    return "\n".join(lines)


async def debug_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    logger.info(f"/debug from user {user.id} (@{user.username})")

    # /debug network
    if context.args and context.args[0].lower() == "network":
        msg = await update.message.reply_text("🌐 Testing network...")
        result = _test_network()
        await msg.delete()
        await update.message.reply_text(
            f"🌐 *Network Test*\n━━━━━━━━━━━━━━━━━━\n{result}\n━━━━━━━━━━━━━━━━━━",
            parse_mode="Markdown",
        )
        return

    # /debug ANTM — ticker spesifik
    if context.args:
        ticker = context.args[0].upper().strip()
        if not ticker.endswith(".JK"):
            ticker += ".JK"
        tickers = [ticker]
    else:
        tickers = DEFAULT_TICKERS

    msg = await update.message.reply_text(f"🔧 Testing {len(tickers)} ticker via Stooq...")

    lines = ["🔧 *Debug: Stooq Data Test*", "━━━━━━━━━━━━━━━━━━"]
    for ticker in tickers:
        result = _fetch_stooq_direct(ticker)
        lines.append(f"\n*{ticker.replace('.JK','')}*: {result}")

    lines.append("\n━━━━━━━━━━━━━━━━━━")
    lines.append("_/debug network → test koneksi internet_")

    await msg.delete()
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

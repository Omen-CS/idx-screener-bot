"""
bot/handlers/debug.py — verbose error version
"""

import logging
import time
import requests
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


def _test_yfinance_direct(ticker: str) -> str:
    """Test yfinance download langsung dengan full error detail."""
    try:
        import yfinance as yf
        import logging as _log
        _log.getLogger("yfinance").setLevel(_log.CRITICAL)

        # Test 1: daily 30d
        raw = yf.download(ticker, period="30d", interval="1d",
                         auto_adjust=True, progress=False)
        if raw is not None and not raw.empty:
            cols = str(raw.columns.tolist())[:60]
            return f"✅ 30d/1d: {len(raw)} bars\ncols: {cols}"

        # Test 2: daily 60d
        time.sleep(1)
        raw2 = yf.download(ticker, period="60d", interval="1d",
                          auto_adjust=True, progress=False)
        if raw2 is not None and not raw2.empty:
            return f"✅ 60d/1d: {len(raw2)} bars"

        return f"❌ Semua period kosong\nshape_30d={raw.shape if raw is not None else 'None'}"

    except Exception as e:
        return f"❌ Exception: {type(e).__name__}: {str(e)[:100]}"


def _test_yahoo_direct(ticker: str) -> str:
    """Hit Yahoo Finance API langsung pakai requests — bypass yfinance."""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=30d"
    try:
        r = requests.get(url, headers=HEADERS, timeout=8)
        if r.status_code == 200:
            data = r.json()
            result = data.get("chart", {}).get("result")
            if result:
                closes = result[0].get("indicators", {}).get("quote", [{}])[0].get("close", [])
                return f"✅ HTTP 200 | {len(closes)} bars | last={closes[-1]:.0f}" if closes else f"✅ HTTP 200 tapi data kosong"
            error = data.get("chart", {}).get("error")
            return f"⚠️ HTTP 200 tapi result None | error={error}"
        return f"❌ HTTP {r.status_code} | {r.text[:80]}"
    except Exception as e:
        return f"❌ {type(e).__name__}: {str(e)[:80]}"


def _test_network() -> str:
    lines = []
    tests = [
        ("Yahoo q1", "https://query1.finance.yahoo.com/v8/finance/chart/BBCA.JK?interval=1d&range=5d"),
        ("Yahoo q2", "https://query2.finance.yahoo.com/v8/finance/chart/BBCA.JK?interval=1d&range=5d"),
        ("Google",   "https://www.google.com"),
        ("Stooq",    "https://stooq.com/q/d/l/?s=bbca.id&i=d"),
    ]
    for name, url in tests:
        try:
            r = requests.get(url, headers=HEADERS, timeout=5)
            preview = r.text[:40].replace('\n', ' ')
            lines.append(f"{'✅' if r.status_code==200 else '⚠️'} {name}: HTTP {r.status_code} | `{preview}`")
        except Exception as e:
            lines.append(f"❌ {name}: {str(e)[:50]}")
    return "\n".join(lines)


async def debug_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    logger.info(f"/debug from user {user.id} (@{user.username})")

    arg = context.args[0].lower() if context.args else ""

    if arg == "network":
        msg = await update.message.reply_text("🌐 Testing network...")
        result = _test_network()
        await msg.delete()
        await update.message.reply_text(
            f"🌐 *Network Test*\n━━━━━━━━━━━━━━━━━━\n{result}\n━━━━━━━━━━━━━━━━━━",
            parse_mode="Markdown",
        )
        return

    if arg == "yahoo":
        msg = await update.message.reply_text("📡 Testing Yahoo API direct...")
        result = _test_yahoo_direct("BBCA.JK")
        await msg.delete()
        await update.message.reply_text(
            f"📡 *Yahoo Direct (BBCA)*\n━━━━━━━━━━━━━━━━━━\n{result}\n━━━━━━━━━━━━━━━━━━",
            parse_mode="Markdown",
        )
        return

    # Default: test yfinance download dengan detail error
    ticker = "BBCA.JK"
    if context.args and arg not in ("network", "yahoo", "stooq"):
        ticker = context.args[0].upper()
        if not ticker.endswith(".JK"):
            ticker += ".JK"

    msg = await update.message.reply_text(f"🔧 Testing yfinance untuk {ticker}...")
    yf_result = _test_yfinance_direct(ticker)
    yahoo_result = _test_yahoo_direct(ticker)

    await msg.delete()
    await update.message.reply_text(
        f"🔧 *Debug: {ticker}*\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"*yfinance:*\n{yf_result}\n\n"
        f"*Yahoo API direct:*\n{yahoo_result}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"_/debug network | /debug yahoo_",
        parse_mode="Markdown",
    )

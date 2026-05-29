"""
bot/handlers/debug.py — dengan intraday test
"""
import logging
import requests
from telegram import Update
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}


def _test_intraday(ticker: str) -> str:
    """Test apakah Yahoo bisa return intraday data dari Railway."""
    lines = []
    tests = [
        ("5m/1d",  f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=5m&range=1d"),
        ("15m/1d", f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=15m&range=1d"),
        ("5m/5d",  f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=5m&range=5d"),
    ]
    for label, url in tests:
        try:
            r = requests.get(url, headers=HEADERS, timeout=8)
            if r.status_code == 200:
                data   = r.json()
                result = data.get("chart", {}).get("result")
                if result:
                    ts     = result[0].get("timestamp", [])
                    closes = result[0].get("indicators", {}).get("quote", [{}])[0].get("close", [])
                    closes = [c for c in closes if c is not None]
                    last   = f"last={closes[-1]:.0f}" if closes else "no closes"
                    lines.append(f"OK {label}: {len(closes)} bars | {last}")
                else:
                    err = data.get("chart", {}).get("error", "unknown")
                    lines.append(f"EMPTY {label}: {err}")
            else:
                lines.append(f"HTTP {r.status_code} {label}")
        except Exception as e:
            lines.append(f"ERROR {label}: {str(e)[:50]}")
    return "\n".join(lines)


def _test_daily(ticker: str) -> str:
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=3mo"
    try:
        r = requests.get(url, headers=HEADERS, timeout=8)
        if r.status_code != 200:
            return f"HTTP {r.status_code}"
        data   = r.json()
        result = data.get("chart", {}).get("result")
        if not result:
            return "result None"
        closes = result[0].get("indicators", {}).get("quote", [{}])[0].get("close", [])
        closes = [c for c in closes if c is not None]
        return f"OK {len(closes)} bars | last={closes[-1]:.0f}" if closes else "no closes"
    except Exception as e:
        return f"ERROR: {str(e)[:50]}"


def _test_network() -> str:
    lines = []
    tests = [
        ("Yahoo q1", "https://query1.finance.yahoo.com/v8/finance/chart/BBCA.JK?interval=1d&range=5d"),
        ("Yahoo q2", "https://query2.finance.yahoo.com/v8/finance/chart/BBCA.JK?interval=1d&range=5d"),
        ("Google",   "https://www.google.com"),
    ]
    for name, url in tests:
        try:
            r = requests.get(url, headers=HEADERS, timeout=5)
            lines.append(f"{'OK' if r.status_code==200 else 'WARN'} {name}: HTTP {r.status_code}")
        except Exception as e:
            lines.append(f"FAIL {name}: {str(e)[:50]}")
    return "\n".join(lines)


async def debug_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    logger.info(f"/debug from user {user.id} (@{user.username})")
    arg = context.args[0].lower() if context.args else ""

    if arg == "network":
        msg = await update.message.reply_text("Testing network...")
        result = _test_network()
        await msg.delete()
        await update.message.reply_text(f"Network Test\n{result}")
        return

    if arg == "intraday":
        ticker = context.args[1].upper() if len(context.args) > 1 else "BBCA.JK"
        if not ticker.endswith(".JK"):
            ticker += ".JK"
        msg = await update.message.reply_text(f"Testing intraday {ticker}...")
        result = _test_intraday(ticker)
        await msg.delete()
        await update.message.reply_text(
            f"Intraday Test: {ticker}\n"
            f"---\n{result}\n---\n"
            f"OK = bisa pakai intraday\n"
            f"HTTP 429 = rate limited\n"
            f"EMPTY = market tutup"
        )
        return

    ticker = "BBCA.JK"
    if context.args and arg not in ("network", "intraday"):
        ticker = context.args[0].upper()
        if not ticker.endswith(".JK"):
            ticker += ".JK"

    msg = await update.message.reply_text(f"Testing {ticker}...")
    daily_result    = _test_daily(ticker)
    intraday_result = _test_intraday(ticker)

    await msg.delete()
    await update.message.reply_text(
        f"Debug: {ticker}\n"
        f"---\nDaily: {daily_result}\n"
        f"---\nIntraday:\n{intraday_result}\n"
        f"---\n/debug intraday BBCA\n/debug network"
    )

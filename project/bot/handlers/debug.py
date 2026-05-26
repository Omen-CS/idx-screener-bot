"""
bot/handlers/debug.py
"""
import logging
import requests
from telegram import Update
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}


def _test_yahoo_requests(ticker: str) -> str:
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=30d"
    try:
        r = requests.get(url, headers=HEADERS, timeout=8)
        if r.status_code != 200:
            return f"HTTP {r.status_code}"
        data = r.json()
        result = data.get("chart", {}).get("result")
        if not result:
            return f"HTTP 200 tapi result None"
        closes = result[0].get("indicators", {}).get("quote", [{}])[0].get("close", [])
        closes = [c for c in closes if c is not None]
        if closes:
            return f"OK {len(closes)} bars, last close={closes[-1]:.0f}"
        return "HTTP 200 tapi close kosong"
    except Exception as e:
        return f"Error: {type(e).__name__}: {str(e)[:80]}"


def _test_fetch_daily(ticker: str) -> str:
    try:
        from services.market_data import fetch_daily, clear_cache
        clear_cache()
        df = fetch_daily(ticker)
        if df is None or df.empty:
            return "kosong"
        close = float(df["Close"].iloc[-1])
        date = str(df.index[-1])[:10]
        return f"OK {len(df)} bars, {date}, close={close:,.0f}"
    except Exception as e:
        return f"Error: {type(e).__name__}: {str(e)[:80]}"


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

    ticker = "BBCA.JK"
    if context.args and arg not in ("network",):
        ticker = context.args[0].upper()
        if not ticker.endswith(".JK"):
            ticker += ".JK"

    msg = await update.message.reply_text(f"Testing {ticker}...")

    yahoo_result  = _test_yahoo_requests(ticker)
    fetch_result  = _test_fetch_daily(ticker)

    await msg.delete()
    await update.message.reply_text(
        f"Debug: {ticker}\n"
        f"---\n"
        f"Yahoo API direct:\n{yahoo_result}\n"
        f"---\n"
        f"market_data.fetch_daily:\n{fetch_result}\n"
        f"---\n"
        f"/debug network untuk test koneksi"
    )

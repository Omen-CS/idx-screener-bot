"""
bot/handlers/debug.py
"""
import logging
import time
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
            err = data.get("chart", {}).get("error", "unknown")
            return f"HTTP 200 tapi result None, error={err}"
        closes = result[0].get("indicators", {}).get("quote", [{}])[0].get("close", [])
        closes = [c for c in closes if c is not None]
        if closes:
            return f"OK {len(closes)} bars, last close={closes[-1]:.0f}"
        return "HTTP 200, result ada tapi close kosong"
    except Exception as e:
        return f"Exception: {type(e).__name__}: {str(e)[:80]}"


def _test_yfinance(ticker: str) -> str:
    try:
        import yfinance as yf
        import logging as _log
        _log.getLogger("yfinance").setLevel(_log.CRITICAL)
        raw = yf.download(ticker, period="30d", interval="1d", auto_adjust=True, progress=False)
        if raw is None:
            return "None returned"
        if raw.empty:
            return f"Empty DataFrame, shape={raw.shape}, cols={list(raw.columns)[:3]}"
        return f"OK {len(raw)} bars, last close={float(raw['Close'].iloc[-1]):.0f}"
    except Exception as e:
        return f"Exception: {type(e).__name__}: {str(e)[:100]}"


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

    yf_result     = _test_yfinance(ticker)
    yahoo_result  = _test_yahoo_requests(ticker)

    import yfinance as yf
    yf_version = getattr(yf, "__version__", "unknown")

    await msg.delete()
    # Pakai plain text — hindari Markdown parse error
    await update.message.reply_text(
        f"Debug: {ticker}\n"
        f"yfinance v{yf_version}\n"
        f"---\n"
        f"yfinance download:\n{yf_result}\n"
        f"---\n"
        f"Yahoo API direct:\n{yahoo_result}\n"
        f"---\n"
        f"/debug network untuk test koneksi"
    )

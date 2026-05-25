"""
bot/handlers/debug.py
/debug — test koneksi + fetch data
Usage: /debug          → test 5 ticker default
       /debug ANTM     → test ticker spesifik
       /debug network  → test koneksi internet saja
"""

import logging
import requests
from telegram import Update
from telegram.ext import ContextTypes
from services.market_data import fetch_intraday, fetch_daily, clear_cache

logger = logging.getLogger(__name__)

DEFAULT_TICKERS = ["BBCA.JK", "BBRI.JK", "ANTM.JK", "TLKM.JK", "GOTO.JK"]


def test_network() -> str:
    """Test apakah Railway bisa akses internet dan domain-domain kunci."""
    results = []
    
    # Test Yahoo Finance
    try:
        r = requests.get("https://query1.finance.yahoo.com/v8/finance/chart/BBCA.JK?interval=1d&range=5d", timeout=5)
        if r.status_code == 200:
            results.append("✅ Yahoo Finance API: OK")
        else:
            results.append(f"⚠️ Yahoo Finance API: HTTP {r.status_code}")
    except Exception as e:
        results.append(f"❌ Yahoo Finance API: {str(e)[:50]}")

    # Test Yahoo query2
    try:
        r = requests.get("https://query2.finance.yahoo.com/v8/finance/chart/BBCA.JK?interval=1d&range=5d", timeout=5)
        if r.status_code == 200:
            results.append("✅ Yahoo query2: OK")
        else:
            results.append(f"⚠️ Yahoo query2: HTTP {r.status_code}")
    except Exception as e:
        results.append(f"❌ Yahoo query2: {str(e)[:50]}")

    # Test Google (baseline internet check)
    try:
        r = requests.get("https://www.google.com", timeout=5)
        results.append(f"✅ Google: OK (HTTP {r.status_code})")
    except Exception as e:
        results.append(f"❌ Google: {str(e)[:50]}")

    # Test Stooq
    try:
        r = requests.get("https://stooq.com/q/d/l/?s=bbca.id&i=d", timeout=5)
        if r.status_code == 200 and "Date" in r.text:
            results.append("✅ Stooq: OK")
        else:
            results.append(f"⚠️ Stooq: HTTP {r.status_code}")
    except Exception as e:
        results.append(f"❌ Stooq: {str(e)[:50]}")

    # Test IDX API
    try:
        r = requests.get("https://idx.co.id/umbraco/Surface/StockData/GetSecuritiesStock?start=0&length=10&code=BBCA", timeout=5)
        if r.status_code == 200:
            results.append("✅ IDX.co.id: OK")
        else:
            results.append(f"⚠️ IDX.co.id: HTTP {r.status_code}")
    except Exception as e:
        results.append(f"❌ IDX.co.id: {str(e)[:50]}")

    return "\n".join(results)


async def debug_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    logger.info(f"/debug from user {user.id} (@{user.username})")

    # /debug network → test koneksi saja
    if context.args and context.args[0].lower() == "network":
        msg = await update.message.reply_text("🌐 Testing network connections...", parse_mode="Markdown")
        net_result = test_network()
        await msg.delete()
        await update.message.reply_text(
            f"🌐 *Network Test*\n━━━━━━━━━━━━━━━━━━\n{net_result}\n━━━━━━━━━━━━━━━━━━",
            parse_mode="Markdown",
        )
        return

    # /debug ANTM → test ticker spesifik
    if context.args:
        ticker_input = context.args[0].upper().strip()
        if not ticker_input.endswith(".JK"):
            ticker_input += ".JK"
        tickers = [ticker_input]
    else:
        tickers = DEFAULT_TICKERS

    msg = await update.message.reply_text(
        f"🔧 Testing {len(tickers)} ticker... harap tunggu.",
    )

    clear_cache()
    lines = ["🔧 *Debug: Data Fetch Test*", "━━━━━━━━━━━━━━━━━━"]

    for ticker in tickers:
        try:
            df5  = fetch_intraday(ticker, "5m")
            df15 = fetch_intraday(ticker, "15m")
            dfd  = fetch_daily(ticker)

            def fmt(df):
                if df is None or df.empty:
                    return "❌ kosong"
                price = df["Close"].iloc[-1]
                return f"✅ {len(df)} bars | close={price:,.0f}"

            lines.append(
                f"\n*{ticker.replace('.JK','')}*\n"
                f"  5m   : {fmt(df5)}\n"
                f"  15m  : {fmt(df15)}\n"
                f"  Daily: {fmt(dfd)}"
            )
        except Exception as e:
            lines.append(f"\n*{ticker}*\n  ⚠️ Error: {str(e)[:80]}")

    lines.append("\n━━━━━━━━━━━━━━━━━━")
    lines.append("_Coba /debug network untuk test koneksi internet_")

    await msg.delete()
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

"""
bot/handlers/debug.py
/debug — test fetch data untuk beberapa ticker liquid.
Usage: /debug        → test 5 ticker default
       /debug ANTM   → test ticker spesifik
"""

import logging
from telegram import Update
from telegram.ext import ContextTypes
from services.market_data import fetch_intraday, fetch_daily, clear_cache

logger = logging.getLogger(__name__)

DEFAULT_TICKERS = ["BBCA.JK", "BBRI.JK", "ANTM.JK", "TLKM.JK", "GOTO.JK"]


async def debug_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    logger.info(f"/debug from user {user.id} (@{user.username})")

    # Cek apakah ada argumen ticker: /debug ANTM
    if context.args:
        ticker_input = context.args[0].upper().strip()
        if not ticker_input.endswith(".JK"):
            ticker_input += ".JK"
        tickers = [ticker_input]
    else:
        tickers = DEFAULT_TICKERS

    msg = await update.message.reply_text(
        f"🔧 Testing {len(tickers)} ticker... harap tunggu.",
        parse_mode="Markdown",
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
                f"  5m  : {fmt(df5)}\n"
                f"  15m : {fmt(df15)}\n"
                f"  Daily: {fmt(dfd)}"
            )
        except Exception as e:
            lines.append(f"\n*{ticker}*\n  ⚠️ Error: {str(e)[:80]}")

    lines.append("\n━━━━━━━━━━━━━━━━━━")
    lines.append("_✅ = data OK | ❌ = kosong/gagal_")
    lines.append("_Kalau semua ❌ → pasar tutup atau rate limit_")

    await msg.delete()
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

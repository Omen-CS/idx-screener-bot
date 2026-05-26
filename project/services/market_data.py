"""
services/market_data.py — Stooq Engine

Yahoo Finance kena rate limit 429 di Railway.
Stooq tersedia (HTTP 200) dan tidak butuh API key.

Stooq hanya punya data DAILY — tidak ada 5m/15m intraday.
Solusi: pakai daily data untuk semua kalkulasi.
Screener logic disesuaikan di scanner.py (lihat MODE_DAILY flag).
"""

import logging
import time
from datetime import datetime
from io import StringIO
from typing import Dict, List, Optional, Tuple

import pandas as pd
import requests

logger = logging.getLogger(__name__)

# Flag global — scanner akan baca ini untuk tahu mode data yang tersedia
DATA_MODE = "daily"   # "intraday" atau "daily"

_cache: Dict[str, Tuple[datetime, pd.DataFrame]] = {}
CACHE_TTL = 1800  # 30 menit


def _cache_fresh(ts: datetime) -> bool:
    return (datetime.now() - ts).total_seconds() < CACHE_TTL


def clear_cache() -> None:
    global _cache
    _cache.clear()
    logger.info("Market data cache cleared")


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}


def _fetch_stooq(ticker: str) -> Optional[pd.DataFrame]:
    """
    Fetch daily OHLCV dari Stooq.
    Ticker format: BBCA.JK → bbca.id
    """
    symbol = ticker.replace(".JK", "").lower()
    url = f"https://stooq.com/q/d/l/?s={symbol}.id&i=d"

    try:
        resp = requests.get(url, headers=HEADERS, timeout=6)
        if resp.status_code != 200:
            logger.debug(f"  Stooq {ticker}: HTTP {resp.status_code}")
            return None

        text = resp.text.strip()
        if "Date" not in text or len(text) < 50:
            logger.debug(f"  Stooq {ticker}: response kosong atau bukan CSV")
            return None

        df = pd.read_csv(StringIO(text))
        if df.empty or len(df) < 3:
            return None

        df["Date"] = pd.to_datetime(df["Date"])
        df.set_index("Date", inplace=True)
        df = df.sort_index()

        # Pastikan kolom lengkap
        required = {"Open", "High", "Low", "Close", "Volume"}
        if not required.issubset(df.columns):
            return None

        df = df[["Open", "High", "Low", "Close", "Volume"]].copy()
        df = df.dropna(subset=["Close"])
        df["Volume"] = pd.to_numeric(df["Volume"], errors="coerce").fillna(0).clip(lower=0)

        return df if not df.empty else None

    except Exception as e:
        logger.debug(f"  Stooq {ticker} error: {e}")
        return None


def fetch_daily(ticker: str) -> Optional[pd.DataFrame]:
    """Return daily OHLCV (last 60 hari)."""
    if ticker in _cache:
        ts, df = _cache[ticker]
        if _cache_fresh(ts):
            return df

    df = _fetch_stooq(ticker)
    if df is not None:
        df = df.tail(60)  # ambil 60 hari terakhir
        _cache[ticker] = (datetime.now(), df)

    return df


def fetch_intraday(ticker: str, interval: str = "5m") -> Optional[pd.DataFrame]:
    """
    Stooq tidak punya intraday — return daily sebagai pengganti.
    Scanner akan deteksi DATA_MODE="daily" dan sesuaikan logic-nya.
    """
    return fetch_daily(ticker)


def fetch_batch(
    tickers: List[str],
    interval: str = "5m",
    batch_size: int = 30,
    sleep_between_batches: float = 0.5,
) -> Dict[str, Tuple[Optional[pd.DataFrame], Optional[pd.DataFrame]]]:
    """
    Fetch data untuk semua ticker dari Stooq.
    Return tuple (df_intraday, df_daily) — keduanya sama (daily data).
    """
    results: Dict[str, Tuple[Optional[pd.DataFrame], Optional[pd.DataFrame]]] = {}
    total = len(tickers)
    valid = 0
    total_batches = (total + batch_size - 1) // batch_size

    logger.info(f"🚀 Stooq ENGINE: {total} tickers, {total_batches} batches")

    for batch_num, start in enumerate(range(0, total, batch_size), 1):
        batch = tickers[start: start + batch_size]
        logger.info(f"📦 Batch {batch_num}/{total_batches} ({start+1}–{min(start+batch_size, total)}/{total})")

        for ticker in batch:
            df = fetch_daily(ticker)
            if df is not None:
                valid += 1
                results[ticker] = (df, df)  # sama — daily untuk keduanya
            else:
                results[ticker] = (None, None)

            time.sleep(0.05)  # 50ms per ticker — cukup sopan ke Stooq

        if start + batch_size < total:
            time.sleep(sleep_between_batches)

    logger.info(f"✅ Stooq fetch complete: {valid}/{total} tickers berhasil")
    return results

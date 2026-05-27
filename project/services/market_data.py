"""
services/market_data.py — Concurrent fetching

Pakai ThreadPoolExecutor untuk download banyak ticker paralel.
950 ticker dengan 20 workers = ~1.5 menit vs 24 menit sequential.

Rate limit strategy:
- Max 20 concurrent requests ke Yahoo
- Retry otomatis kalau 429
- Cache 30 menit
"""

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import pandas as pd
import requests

logger = logging.getLogger(__name__)

DATA_MODE = "daily"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
}

_cache: Dict[str, Tuple[datetime, pd.DataFrame]] = {}
CACHE_TTL = 1800  # 30 menit
MAX_WORKERS = 20  # concurrent requests


def _cache_fresh(ts: datetime) -> bool:
    return (datetime.now() - ts).total_seconds() < CACHE_TTL


def clear_cache() -> None:
    global _cache
    _cache.clear()
    logger.info("Cache cleared")


def _fetch_yahoo(ticker: str, retries: int = 2) -> Optional[pd.DataFrame]:
    """
    Fetch daily OHLCV dari Yahoo Finance API.
    Auto-retry kalau kena 429.
    """
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
        f"?interval=1d&range=3mo"
    )

    for attempt in range(retries + 1):
        try:
            r = requests.get(url, headers=HEADERS, timeout=8)

            if r.status_code == 429:
                wait = 3 * (attempt + 1)
                logger.debug(f"  {ticker}: 429, retry in {wait}s")
                time.sleep(wait)
                continue

            if r.status_code != 200:
                return None

            data = r.json()
            result = data.get("chart", {}).get("result")
            if not result:
                return None

            chart      = result[0]
            timestamps = chart.get("timestamp", [])
            quote      = chart.get("indicators", {}).get("quote", [{}])[0]

            df = pd.DataFrame({
                "Open":   quote.get("open", []),
                "High":   quote.get("high", []),
                "Low":    quote.get("low", []),
                "Close":  quote.get("close", []),
                "Volume": quote.get("volume", []),
            }, index=pd.to_datetime(timestamps, unit="s", utc=True).tz_convert("Asia/Jakarta"))

            df = df.dropna(subset=["Close"])
            df["Volume"] = df["Volume"].fillna(0).clip(lower=0)

            return df if not df.empty else None

        except Exception as e:
            logger.debug(f"  {ticker} attempt {attempt}: {e}")
            if attempt < retries:
                time.sleep(1)

    return None


def fetch_daily(ticker: str) -> Optional[pd.DataFrame]:
    key = f"{ticker}_daily"
    if key in _cache and _cache_fresh(_cache[key][0]):
        return _cache[key][1]

    df = _fetch_yahoo(ticker)
    if df is not None:
        _cache[key] = (datetime.now(), df)
    return df


def fetch_intraday(ticker: str, interval: str = "5m") -> Optional[pd.DataFrame]:
    return fetch_daily(ticker)


def _fetch_one(ticker: str) -> Tuple[str, Optional[pd.DataFrame]]:
    """Worker function untuk ThreadPoolExecutor."""
    df = fetch_daily(ticker)
    return ticker, df


def fetch_batch(
    tickers: List[str],
    interval: str = "5m",
    batch_size: int = None,       # tidak dipakai, kept for compatibility
    sleep_between_batches: float = None,
) -> Dict[str, Tuple[Optional[pd.DataFrame], Optional[pd.DataFrame]]]:
    """
    Fetch data semua ticker secara concurrent.

    Pakai ThreadPoolExecutor dengan MAX_WORKERS=20 thread paralel.
    950 ticker / 20 workers = ~48 batch kecil, jauh lebih cepat.
    """
    results: Dict[str, Tuple[Optional[pd.DataFrame], Optional[pd.DataFrame]]] = {}
    total = len(tickers)
    valid = 0

    logger.info(f"Fetching {total} tickers concurrent ({MAX_WORKERS} workers)")

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(_fetch_one, ticker): ticker for ticker in tickers}

        completed = 0
        for future in as_completed(futures):
            ticker, df = future.result()
            results[ticker] = (df, df)
            if df is not None:
                valid += 1
            completed += 1
            if completed % 100 == 0 or completed == total:
                logger.info(f"  Progress: {completed}/{total} ({valid} valid)")

    logger.info(f"Done: {valid}/{total} tickers berhasil")
    return results

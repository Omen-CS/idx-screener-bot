"""
services/market_data.py — Direct Yahoo Finance API

yfinance gagal untuk ticker .JK (return empty DataFrame).
Yahoo Finance API langsung via requests bekerja dengan baik (HTTP 200, 29 bars).

Endpoint: https://query1.finance.yahoo.com/v8/finance/chart/{ticker}
"""

import logging
import time
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


def _cache_fresh(ts: datetime) -> bool:
    return (datetime.now() - ts).total_seconds() < CACHE_TTL


def clear_cache() -> None:
    global _cache
    _cache.clear()
    logger.info("Cache cleared")


def _fetch_yahoo(ticker: str, interval: str = "1d", range_: str = "3mo") -> Optional[pd.DataFrame]:
    """
    Fetch OHLCV langsung dari Yahoo Finance v8 API.
    Jauh lebih reliable daripada yfinance library untuk ticker .JK.
    """
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
        f"?interval={interval}&range={range_}"
    )
    try:
        r = requests.get(url, headers=HEADERS, timeout=8)
        if r.status_code == 429:
            logger.warning(f"  {ticker}: rate limited (429), tunggu 5s")
            time.sleep(5)
            r = requests.get(url, headers=HEADERS, timeout=8)

        if r.status_code != 200:
            logger.debug(f"  {ticker}: HTTP {r.status_code}")
            return None

        data = r.json()
        result = data.get("chart", {}).get("result")
        if not result:
            logger.debug(f"  {ticker}: result None")
            return None

        chart = result[0]
        timestamps = chart.get("timestamp", [])
        quote = chart.get("indicators", {}).get("quote", [{}])[0]

        opens   = quote.get("open", [])
        highs   = quote.get("high", [])
        lows    = quote.get("low", [])
        closes  = quote.get("close", [])
        volumes = quote.get("volume", [])

        if not timestamps or not closes:
            return None

        df = pd.DataFrame({
            "Open":   opens,
            "High":   highs,
            "Low":    lows,
            "Close":  closes,
            "Volume": volumes,
        }, index=pd.to_datetime(timestamps, unit="s", utc=True).tz_convert("Asia/Jakarta"))

        # Hapus baris dengan Close = NaN
        df = df.dropna(subset=["Close"])
        df["Volume"] = df["Volume"].fillna(0).clip(lower=0)

        if df.empty:
            return None

        return df

    except Exception as e:
        logger.debug(f"  {ticker} fetch error: {e}")
        return None


def fetch_daily(ticker: str) -> Optional[pd.DataFrame]:
    """Return daily OHLCV 3 bulan terakhir."""
    key = f"{ticker}_daily"
    if key in _cache and _cache_fresh(_cache[key][0]):
        return _cache[key][1]

    df = _fetch_yahoo(ticker, interval="1d", range_="3mo")
    if df is None:
        time.sleep(1)
        df = _fetch_yahoo(ticker, interval="1d", range_="1mo")

    if df is not None:
        _cache[key] = (datetime.now(), df)
    return df


def fetch_intraday(ticker: str, interval: str = "5m") -> Optional[pd.DataFrame]:
    """Fallback ke daily — Yahoo 429 untuk intraday di Railway."""
    return fetch_daily(ticker)


def fetch_batch(
    tickers: List[str],
    interval: str = "5m",
    batch_size: int = 10,
    sleep_between_batches: float = 3.0,
) -> Dict[str, Tuple[Optional[pd.DataFrame], Optional[pd.DataFrame]]]:
    """
    Fetch daily data untuk semua ticker.
    Delay 1.5 detik per ticker supaya tidak kena 429.
    """
    results: Dict[str, Tuple[Optional[pd.DataFrame], Optional[pd.DataFrame]]] = {}
    total = len(tickers)
    valid = 0
    total_batches = (total + batch_size - 1) // batch_size

    logger.info(f"Fetching {total} tickers via Yahoo API direct")

    for batch_num, start in enumerate(range(0, total, batch_size), 1):
        batch = tickers[start: start + batch_size]
        logger.info(
            f"Batch {batch_num}/{total_batches} "
            f"({start+1}-{min(start+batch_size, total)}/{total})"
        )

        for ticker in batch:
            df = fetch_daily(ticker)
            results[ticker] = (df, df)
            if df is not None:
                valid += 1
            time.sleep(1.5)  # 1.5 detik per ticker

        if start + batch_size < total:
            time.sleep(sleep_between_batches)

    logger.info(f"Done: {valid}/{total} tickers berhasil")
    return results

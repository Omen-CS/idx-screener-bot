"""
services/market_data.py — Intraday + Daily

Sekarang pakai intraday (5m/15m) untuk BPJS/BSJP scan.
Daily tetap dipakai untuk kalkulasi EMA, RSI, relative volume baseline.

fetch_intraday() → 5m atau 15m data hari ini
fetch_daily()    → daily data 3 bulan untuk indicator baseline
"""

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import pandas as pd
import requests

logger = logging.getLogger(__name__)

DATA_MODE = "intraday"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
}

_cache: Dict[str, Tuple[datetime, pd.DataFrame]] = {}
INTRADAY_TTL = 180   # 3 menit — refresh sering untuk early detection
DAILY_TTL    = 3600  # 60 menit

MAX_WORKERS = 20


def _cache_fresh(ts: datetime, ttl: int) -> bool:
    return (datetime.now() - ts).total_seconds() < ttl


def clear_cache() -> None:
    global _cache
    _cache.clear()
    logger.info("Cache cleared")


def _parse_yahoo_response(r: requests.Response) -> Optional[pd.DataFrame]:
    """Parse Yahoo Finance v8 API response jadi DataFrame OHLCV."""
    if r.status_code != 200:
        return None

    try:
        data   = r.json()
        result = data.get("chart", {}).get("result")
        if not result:
            return None

        chart      = result[0]
        timestamps = chart.get("timestamp", [])
        quote      = chart.get("indicators", {}).get("quote", [{}])[0]

        if not timestamps:
            return None

        df = pd.DataFrame({
            "Open":   quote.get("open", []),
            "High":   quote.get("high", []),
            "Low":    quote.get("low", []),
            "Close":  quote.get("close", []),
            "Volume": quote.get("volume", []),
        }, index=pd.to_datetime(timestamps, unit="s", utc=True)
                  .tz_convert("Asia/Jakarta"))

        df = df.dropna(subset=["Close"])
        df["Volume"] = df["Volume"].fillna(0).clip(lower=0)

        return df if not df.empty else None

    except Exception as e:
        logger.debug(f"Parse error: {e}")
        return None


def _fetch(url: str, retries: int = 2) -> Optional[pd.DataFrame]:
    """Fetch satu URL dengan retry kalau 429."""
    for attempt in range(retries + 1):
        try:
            r = requests.get(url, headers=HEADERS, timeout=8)
            if r.status_code == 429:
                wait = 3 * (attempt + 1)
                logger.debug(f"429, retry in {wait}s")
                time.sleep(wait)
                continue
            return _parse_yahoo_response(r)
        except Exception as e:
            logger.debug(f"Fetch error attempt {attempt}: {e}")
            if attempt < retries:
                time.sleep(1)
    return None


def fetch_intraday(ticker: str, interval: str = "5m") -> Optional[pd.DataFrame]:
    """
    Fetch intraday OHLCV (5m atau 15m) untuk hari ini.
    Fallback ke 5d kalau 1d kosong (weekend/holiday).
    """
    key = f"{ticker}_{interval}_intraday"
    if key in _cache and _cache_fresh(_cache[key][0], INTRADAY_TTL):
        return _cache[key][1]

    # Coba 1d dulu
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval={interval}&range=1d"
    df  = _fetch(url)

    # Fallback ke 5d kalau kosong (market baru buka / holiday)
    if df is None or df.empty or len(df) < 3:
        url2 = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval={interval}&range=5d"
        df2  = _fetch(url2)
        if df2 is not None and not df2.empty:
            # Ambil hanya hari terakhir
            try:
                last_date = df2.index[-1].date()
                df_day    = df2[df2.index.date == last_date]
                df        = df_day if len(df_day) >= 3 else df2.tail(20)
            except Exception:
                df = df2.tail(20)

    if df is not None and not df.empty:
        _cache[key] = (datetime.now(), df)

    return df


def fetch_daily(ticker: str) -> Optional[pd.DataFrame]:
    """
    Fetch daily OHLCV 3 bulan untuk baseline indicator.
    Dipakai untuk: EMA20, RSI, relative volume baseline, resistance level.
    """
    key = f"{ticker}_daily"
    if key in _cache and _cache_fresh(_cache[key][0], DAILY_TTL):
        return _cache[key][1]

    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=3mo"
    df  = _fetch(url)

    if df is None or df.empty:
        url2 = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=6mo"
        df   = _fetch(url2)

    if df is not None and not df.empty:
        _cache[key] = (datetime.now(), df)

    return df


def _fetch_one(ticker: str, interval: str) -> Tuple[str, Optional[pd.DataFrame], Optional[pd.DataFrame]]:
    """Worker: fetch intraday + daily untuk satu ticker."""
    df_intraday = fetch_intraday(ticker, interval)
    df_daily    = fetch_daily(ticker)
    return ticker, df_intraday, df_daily


def fetch_batch(
    tickers: List[str],
    interval: str = "5m",
    batch_size: int = None,
    sleep_between_batches: float = None,
) -> Dict[str, Tuple[Optional[pd.DataFrame], Optional[pd.DataFrame]]]:
    """
    Concurrent fetch intraday + daily untuk semua ticker.
    Return: {ticker: (df_intraday, df_daily)}
    """
    results: Dict[str, Tuple[Optional[pd.DataFrame], Optional[pd.DataFrame]]] = {}
    total        = len(tickers)
    valid_intra  = 0
    valid_daily  = 0

    logger.info(f"Fetching {total} tickers — intraday({interval}) + daily | {MAX_WORKERS} workers")

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(_fetch_one, ticker, interval): ticker
            for ticker in tickers
        }
        completed = 0
        for future in as_completed(futures):
            try:
                ticker, df_i, df_d = future.result()
                results[ticker] = (df_i, df_d)
                if df_i is not None and not df_i.empty: valid_intra += 1
                if df_d is not None and not df_d.empty: valid_daily += 1
            except Exception as e:
                ticker = futures[future]
                logger.debug(f"Worker error {ticker}: {e}")
                results[ticker] = (None, None)
            completed += 1
            if completed % 100 == 0 or completed == total:
                logger.info(f"  Progress: {completed}/{total}")

    logger.info(f"Done: {valid_intra}/{total} intraday | {valid_daily}/{total} daily")
    return results

"""
services/market_data.py
yfinance dengan anti-429 strategy: 2 detik delay per ticker, 50 ticker max.
"""

import logging
import time
import warnings
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import pandas as pd
import yfinance as yf

warnings.filterwarnings("ignore", category=FutureWarning)
logging.getLogger("yfinance").setLevel(logging.CRITICAL)

logger = logging.getLogger(__name__)

# Flag untuk scanner — pakai daily data
DATA_MODE = "daily"

_cache: Dict[str, Tuple[datetime, pd.DataFrame]] = {}
CACHE_TTL = 1800  # 30 menit


def _cache_fresh(ts: datetime) -> bool:
    return (datetime.now() - ts).total_seconds() < CACHE_TTL


def clear_cache() -> None:
    global _cache
    _cache.clear()
    logger.info("Cache cleared")


def _flatten(df: pd.DataFrame) -> Optional[pd.DataFrame]:
    if df is None or df.empty:
        return None
    if isinstance(df.columns, pd.MultiIndex):
        df = df.copy()
        df.columns = [str(c[0]).strip() for c in df.columns]
    col_map = {}
    for c in df.columns:
        lc = c.lower().strip()
        if lc == "open":   col_map[c] = "Open"
        elif lc == "high": col_map[c] = "High"
        elif lc == "low":  col_map[c] = "Low"
        elif lc in ("close", "adj close", "adjclose"): col_map[c] = "Close"
        elif lc == "volume": col_map[c] = "Volume"
    df = df.rename(columns=col_map)
    required = {"Open", "High", "Low", "Close", "Volume"}
    if not required.issubset(df.columns):
        return None
    df = df[list(required)].copy()
    df = df.dropna(subset=["Close"])
    df = df.ffill().dropna(subset=["Open", "High", "Low", "Close"])
    df["Volume"] = pd.to_numeric(df["Volume"], errors="coerce").fillna(0).clip(lower=0)
    return df if not df.empty else None


def _download_one(ticker: str, interval: str, period: str) -> Optional[pd.DataFrame]:
    try:
        raw = yf.download(
            ticker,
            period=period,
            interval=interval,
            auto_adjust=True,
            progress=False,
        )
        return _flatten(raw)
    except Exception as e:
        logger.debug(f"  {ticker} [{interval}/{period}]: {e}")
        return None


def fetch_daily(ticker: str) -> Optional[pd.DataFrame]:
    key = f"{ticker}_daily"
    if key in _cache and _cache_fresh(_cache[key][0]):
        return _cache[key][1]
    df = _download_one(ticker, "1d", "30d")
    if df is None:
        time.sleep(1)
        df = _download_one(ticker, "1d", "60d")
    if df is not None:
        _cache[key] = (datetime.now(), df)
    return df


def fetch_intraday(ticker: str, interval: str = "5m") -> Optional[pd.DataFrame]:
    """Stooq tidak tersedia, Yahoo 429 untuk intraday — pakai daily sebagai fallback."""
    return fetch_daily(ticker)


def fetch_batch(
    tickers: List[str],
    interval: str = "5m",
    batch_size: int = 10,
    sleep_between_batches: float = 5.0,
) -> Dict[str, Tuple[Optional[pd.DataFrame], Optional[pd.DataFrame]]]:
    results: Dict[str, Tuple[Optional[pd.DataFrame], Optional[pd.DataFrame]]] = {}
    total = len(tickers)
    valid = 0
    total_batches = (total + batch_size - 1) // batch_size

    logger.info(f"🚀 Fetching {total} tickers (2s delay per ticker, anti-429)")

    for batch_num, start in enumerate(range(0, total, batch_size), 1):
        batch = tickers[start: start + batch_size]
        logger.info(f"📦 Batch {batch_num}/{total_batches} ({start+1}–{min(start+batch_size, total)}/{total})")

        for ticker in batch:
            df = fetch_daily(ticker)
            results[ticker] = (df, df)
            if df is not None:
                valid += 1
            time.sleep(2.0)  # 2 detik per ticker supaya tidak kena 429

        if start + batch_size < total:
            logger.info(f"  ⏳ Jeda {sleep_between_batches}s antar batch...")
            time.sleep(sleep_between_batches)

    logger.info(f"✅ Done: {valid}/{total} tickers berhasil")
    return results

"""
services/market_data.py
Handles all market data fetching from yfinance.
"""

import logging
import time
import pandas as pd
import yfinance as yf
from typing import Dict, List, Optional, Tuple
from datetime import datetime

from config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# In-memory cache: {ticker: (timestamp, df_intraday, df_daily)}
# Cache TTL = 5 minutes for intraday, 60 minutes for daily
# ---------------------------------------------------------------------------
_intraday_cache: Dict[str, Tuple[datetime, pd.DataFrame]] = {}
_daily_cache: Dict[str, Tuple[datetime, pd.DataFrame]] = {}

INTRADAY_CACHE_TTL_SECONDS = 300   # 5 minutes
DAILY_CACHE_TTL_SECONDS = 3600     # 60 minutes


def _is_cache_valid(cached_time: datetime, ttl_seconds: int) -> bool:
    """Returns True if cache entry is still fresh."""
    return (datetime.now() - cached_time).total_seconds() < ttl_seconds


def clear_cache() -> None:
    """Clears all cached data. Called between scan runs."""
    global _intraday_cache, _daily_cache
    _intraday_cache.clear()
    _daily_cache.clear()
    logger.info("Market data cache cleared")


def fetch_intraday(ticker: str, interval: str = "5m") -> Optional[pd.DataFrame]:
    """Fetches intraday OHLCV data for a single ticker."""
    cache_key = f"{ticker}_{interval}"

    if cache_key in _intraday_cache:
        cached_time, cached_df = _intraday_cache[cache_key]
        if _is_cache_valid(cached_time, INTRADAY_CACHE_TTL_SECONDS):
            return cached_df

    try:
        df = yf.download(
            ticker,
            period=settings.INTRADAY_PERIOD,
            interval=interval,
            auto_adjust=True,
            progress=False,
            show_errors=False,
        )

        if df is None or df.empty:
            return None

        # Perbaikan MultiIndex yfinance v0.2+
        if isinstance(df.columns, pd.MultiIndex):
            if ticker in df.columns.get_level_values(1):
                df = df.xs(ticker, axis=1, level=1)
            else:
                df.columns = df.columns.get_level_values(0)

        required = {"Open", "High", "Low", "Close", "Volume"}
        if not required.issubset(df.columns):
            return None

        df = df.dropna(subset=["Open", "High", "Low", "Close"])

        if df.empty:
            return None

        _intraday_cache[cache_key] = (datetime.now(), df)
        return df

    except Exception as e:
        logger.debug(f"Failed to fetch intraday data for {ticker}: {e}")
        return None


def fetch_daily(ticker: str) -> Optional[pd.DataFrame]:
    """Fetches daily OHLCV data for a single ticker (last 30 days)."""
    cache_key = f"{ticker}_daily"

    if cache_key in _daily_cache:
        cached_time, cached_df = _daily_cache[cache_key]
        if _is_cache_valid(cached_time, DAILY_CACHE_TTL_SECONDS):
            return cached_df

    try:
        df = yf.download(
            ticker,
            period=settings.DAILY_PERIOD,
            interval="1d",
            auto_adjust=True,
            progress=False,
            show_errors=False,
        )

        if df is None or df.empty:
            return None

        # Perbaikan MultiIndex yfinance v0.2+
        if isinstance(df.columns, pd.MultiIndex):
            if ticker in df.columns.get_level_values(1):
                df = df.xs(ticker, axis=1, level=1)
            else:
                df.columns = df.columns.get_level_values(0)

        required = {"Open", "High", "Low", "Close", "Volume"}
        if not required.issubset(df.columns):
            return None

        df = df.dropna(subset=["Open", "High", "Low", "Close"])

        if df.empty:
            return None

        _daily_cache[cache_key] = (datetime.now(), df)
        return df

    except Exception as e:
        logger.debug(f"Failed to fetch daily data for {ticker}: {e}")
        return None


def fetch_batch(
    tickers: List[str],
    interval: str = "5m",
    batch_size: int = None,
    sleep_between_batches: float = None,
) -> Dict[str, Tuple[Optional[pd.DataFrame], Optional[pd.DataFrame]]]:
    """Fetches intraday + daily data for a list of tickers in batches."""
    if batch_size is None:
        batch_size = settings.TICKER_BATCH_SIZE
    if sleep_between_batches is None:
        sleep_between_batches = settings.BATCH_SLEEP_SECONDS

    results: Dict[str, Tuple[Optional[pd.DataFrame], Optional[pd.DataFrame]]] = {}
    total = len(tickers)

    logger.info(f"Fetching data for {total} tickers in batches of {batch_size}")

    for batch_start in range(0, total, batch_size):
        batch = tickers[batch_start: batch_start + batch_size]
        batch_num = (batch_start // batch_size) + 1
        total_batches = (total + batch_size - 1) // batch_size

        logger.info(f"Processing batch {batch_num}/{total_batches} ({len(batch)} tickers)")

        for ticker in batch:
            df_intraday = fetch_intraday(ticker, interval)
            df_daily = fetch_daily(ticker)
            results[ticker] = (df_intraday, df_daily)

        if batch_start + batch_size < total:
            time.sleep(sleep_between_batches)

    logger.info(f"Data fetch complete. {sum(1 for v in results.values() if v[0] is not None)} tickers had valid intraday data.")
    return results


def get_stock_info(ticker: str) -> Dict:
    """Fetches basic stock info (name, sector, etc.) from yfinance."""
    try:
        info = yf.Ticker(ticker).info
        return {
            "name": info.get("longName", ticker.replace(".JK", "")),
            "sector": info.get("sector", "Unknown"),
            "market_cap": info.get("marketCap", 0),
        }
    except Exception:
        return {
            "name": ticker.replace(".JK", ""),
            "sector": "Unknown",
            "market_cap": 0,
        }

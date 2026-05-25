"""
services/market_data.py
Handles all market data fetching from yfinance.

Features:
- Batched downloading to respect rate limits
- In-memory caching to avoid redundant downloads
- Error handling and retry logic
- Optimized for Railway free tier (minimal memory/CPU)
"""

import logging
import time
import pandas as pd
import yfinance as yf
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta

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
    """
    Fetches intraday OHLCV data for a single ticker.
    """
    cache_key = f"{ticker}_{interval}"

    # Check cache
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

        # CARA BARU: Hancurkan MultiIndex yfinance v0.2+ agar kembali ke dataframe normal
        if isinstance(df.columns, pd.MultiIndex):
            # Jika kolom bertingkat (Price, Ticker), kita ambil tingkat Price-nya saja
            if ticker in df.columns.get_level_values(1):
                df = df.xs(ticker, axis=1, level=1)
            else:
                df.columns = df.columns.get_level_values(0)

        # Ensure required columns exist
        required = {"Open", "High", "Low", "Close", "Volume"}
        if not required.issubset(df.columns):
            logger.debug(f"Ticker {ticker} missing columns: {df.columns}")
            return None

        # Drop rows with NaN in critical columns
        df = df.dropna(subset=["Open", "High", "Low", "Close"])

        if df.empty:
            return None

        # Cache result
        _intraday_cache[cache_key] = (datetime.now(), df)
        return df

    except Exception as e:
        logger.debug(f"Failed to fetch intraday data for {ticker}: {e}")
        return None



def fetch_daily(ticker: str) -> Optional[pd.DataFrame]:
    """
    Fetches daily OHLCV data for a single ticker (last 30 days).

    Args:
        ticker: Stock ticker (e.g. 'ANTM.JK')

    Returns:
        pd.DataFrame or None if fetch failed
    """
    cache_key = f"{ticker}_daily"

    # Check cache
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

        # Flatten MultiIndex columns if present
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        required = {"Open", "High", "Low", "Close", "Volume"}
        if not required.issubset(df.columns):
            return None

        df = df.dropna(subset=["Open", "High", "Low", "Close"])

        if df.empty:
            return None

        # Cache result
        _daily_cache[cache_key] = (datetime.now(), df)
        return df

    except Exception as e:
        logger.debug(f"Failed to fetch daily data for {ticker}: {e}")
        return None


def fetch_daily(ticker: str) -> Optional[pd.DataFrame]:
    """
    Fetches daily OHLCV data for a single ticker (last 30 days).
    """
    cache_key = f"{ticker}_daily"

    # Check cache
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

        # CARA BARU: Hancurkan MultiIndex yfinance v0.2+ agar kembali ke dataframe normal
        if isinstance(df.columns, pd.MultiIndex):
            if ticker in df.columns.get_level_values(1):
                df = df.xs(ticker, axis=1, level=1)
            else:
                df.columns = df.columns.get_level_values(0)

        required = {"Open", "High", "Low", "Close", "Volume"}
        if not required.issubset(df.columns):
            logger.debug(f"Ticker {ticker} daily missing columns: {df.columns}")
            return None

        df = df.dropna(subset=["Open", "High", "Low", "Close"])

        if df.empty:
            return None

        # Cache result
        _daily_cache[cache_key] = (datetime.now(), df)
        return df

    except Exception as e:
        logger.debug(f"Failed to fetch daily data for {ticker}: {e}")
        return None


def get_stock_info(ticker: str) -> Dict:
    """
    Fetches basic stock info (name, sector, etc.) from yfinance.
    Used for display purposes only.

    Args:
        ticker: Stock ticker symbol

    Returns:
        Dict with stock info fields
    """
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

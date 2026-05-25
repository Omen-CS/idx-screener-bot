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

        # 🔍 BARIS TRACKING: Tampilkan tipe kolom asli di log Railway lu
        logger.info(f"=== TRACKING {ticker} === Columns Type: {type(df.columns)} | Columns List: {list(df.columns)}")

        # Perbaikan MultiIndex yfinance v0.2+
        if isinstance(df.columns, pd.MultiIndex):
            if ticker in df.columns.get_level_values(1):
                df = df.xs(ticker, axis=1, level=1)
            else:
                df.columns = df.columns.get_level_values(0)

        required = {"Open", "High", "Low", "Close", "Volume"}
        if not required.issubset(df.columns):
            # 🔍 BARIS TRACKING: Kasih tahu kalau dia gagal lolos saringan kolom
            logger.info(f"❌ {ticker} dibuang karena kolom gak cocok: {list(df.columns)}")
            return None

        df = df.dropna(subset=["Open", "High", "Low", "Close"])

        if df.empty:
            return None

        _intraday_cache[cache_key] = (datetime.now(), df)
        return df

    except Exception as e:
        # 🔍 BARIS TRACKING: Tangkap kalau ada error hancur di tengah jalan
        logger.info(f"💥 ERROR TOTAL di {ticker}: {str(e)}")
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
    """
    Fetches market data using yfinance's native batch download for extreme speed.
    Prevents Railway timeouts and fixes MultiIndex columns instantly.
    """
    if batch_size is None:
        batch_size = settings.TICKER_BATCH_SIZE if hasattr(settings, 'TICKER_BATCH_SIZE') else 20
    if sleep_between_batches is None:
        sleep_between_batches = settings.BATCH_SLEEP_SECONDS if hasattr(settings, 'BATCH_SLEEP_SECONDS') else 1.0

    results: Dict[str, Tuple[Optional[pd.DataFrame], Optional[pd.DataFrame]]] = {}
    total = len(tickers)

    logger.info(f"🚀 NATIVE BATCH: Fetching {total} tickers in batches of {batch_size}")

    for batch_start in range(0, total, batch_size):
        batch = tickers[batch_start: batch_start + batch_size]
        batch_num = (batch_start // batch_size) + 1
        total_batches = (total + batch_size - 1) // batch_size

        logger.info(f"📦 Processing batch {batch_num}/{total_batches} ({len(batch)} tickers)...")

        try:
            # 1. Download INTRADAY secara massal (1 kali request untuk 20 ticker)
            df_intraday_all = yf.download(
                tickers=batch,
                period=settings.INTRADAY_PERIOD,
                interval=interval,
                group_by="ticker",  # Mengelompokkan kolom berdasarkan ticker
                auto_adjust=True,
                progress=False
            )

            # 2. Download DAILY secara massal (1 kali request untuk 20 ticker)
            df_daily_all = yf.download(
                tickers=batch,
                period=settings.DAILY_PERIOD,
                interval="1d",
                group_by="ticker",
                auto_adjust=True,
                progress=False
            )

            # Extract data per ticker dari hasil download massal
            for ticker in batch:
                df_in = None
                df_da = None

                # Ekstrak data intraday ticker ini
                if df_intraday_all is not None and not df_intraday_all.empty:
                    if len(batch) == 1:
                        df_in = df_intraday_all.copy()
                    elif ticker in df_intraday_all.columns.get_level_values(0):
                        df_in = df_intraday_all[ticker].copy()
                    
                    if df_in is not None and not df_in.empty:
                        df_in = df_in.dropna(subset=["Open", "High", "Low", "Close"])

                # Ekstrak data daily ticker ini
                if df_daily_all is not None and not df_daily_all.empty:
                    if len(batch) == 1:
                        df_da = df_daily_all.copy()
                    elif ticker in df_daily_all.columns.get_level_values(0):
                        df_da = df_daily_all[ticker].copy()
                    
                    if df_da is not None and not df_da.empty:
                        df_da = df_da.dropna(subset=["Open", "High", "Low", "Close"])

                # Cek kelayakan kolom data
                required = {"Open", "High", "Low", "Close", "Volume"}
                valid_in = df_in is not None and not df_in.empty and required.issubset(df_in.columns)
                valid_da = df_da is not None and not df_da.empty and required.issubset(df_da.columns)

                if valid_in and valid_da:
                    results[ticker] = (df_in, df_da)
                else:
                    results[ticker] = (None, None)

        except Exception as e:
            logger.info(f"💥 Error processing batch {batch_num}: {e}")
            for ticker in batch:
                results[ticker] = (None, None)

        # Kasih jeda pendek biar gak di-ban Yahoo
        if batch_start + batch_size < total:
            time.sleep(sleep_between_batches)

    valid_count = sum(1 for v in results.values() if v[0] is not None)
    logger.info(f"✅ Data fetch complete! {valid_count} tickers successfully fetched and validated.")
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

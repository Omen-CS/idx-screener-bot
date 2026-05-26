"""
services/market_data.py — Final Version

Yahoo Finance (yfinance) adalah satu-satunya opsi yang tersedia di Railway:
- Stooq: butuh API key (berbayar) sejak 2025
- IDX API: 403 Forbidden
- Google Finance: tidak ada library resmi

Solusi rate limit 429:
- Download SATU ticker per request (bukan bulk) tapi dengan delay 2 detik
- Hanya scan 50 ticker paling liquid (bukan 218)
- Cache agresif 30 menit supaya tidak re-download
- Retry sekali kalau gagal
"""

import logging
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

# Matikan warning deprecated yfinance
import warnings
warnings.filterwarnings("ignore", category=FutureWarning)
yf.utils.get_json = yf.utils.get_json  # suppress show_errors warning

_cache: Dict[str, Tuple[datetime, pd.DataFrame]] = {}
CACHE_TTL = 1800  # 30 menit — agresif supaya tidak re-download


def _cache_fresh(ts: datetime) -> bool:
    return (datetime.now() - ts).total_seconds() < CACHE_TTL


def clear_cache() -> None:
    global _cache
    _cache.clear()
    logger.info("Cache cleared")


def _flatten(df: pd.DataFrame) -> Optional[pd.DataFrame]:
    """Normalise yfinance MultiIndex columns → OHLCV flat DataFrame."""
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
    """Download satu ticker, return None kalau gagal."""
    try:
        import logging as _log
        _log.getLogger("yfinance").setLevel(_log.CRITICAL)

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
    """Return daily OHLCV 30 hari terakhir."""
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
    """Return intraday OHLCV hari terakhir trading."""
    key = f"{ticker}_{interval}"
    if key in _cache and _cache_fresh(_cache[key][0]):
        return _cache[key][1]

    df = _download_one(ticker, interval, "1d")
    if df is None:
        time.sleep(1)
        df = _download_one(ticker, interval, "5d")

    if df is not None:
        # Filter hanya hari terakhir
        if hasattr(df.index, "date") and not df.empty:
            try:
                last_date = df.index[-1].date()
                day_df = df[df.index.date == last_date]
                if len(day_df) >= 2:
                    df = day_df
            except Exception:
                pass
        _cache[key] = (datetime.now(), df)
    return df


def fetch_batch(
    tickers: List[str],
    interval: str = "5m",
    batch_size: int = 10,
    sleep_between_batches: float = 5.0,
) -> Dict[str, Tuple[Optional[pd.DataFrame], Optional[pd.DataFrame]]]:
    """
    Fetch daily data untuk semua ticker.

    Strategy anti-429:
    - 10 ticker per batch
    - Delay 2 detik antar ticker dalam batch
    - Delay 5 detik antar batch
    - Cache 30 menit supaya /bpjs dan /bsjp tidak double-fetch

    Total waktu untuk 50 ticker:
    5 batch × (10 ticker × 2s + 5s jeda) = 5 × 25s = ~125 detik (~2 menit)
    """
    results: Dict[str, Tuple[Optional[pd.DataFrame], Optional[pd.DataFrame]]] = {}
    total = len(tickers)
    valid = 0
    total_batches = (total + batch_size - 1) // batch_size

    logger.info(f"🚀 Fetching {total} tickers via yfinance (anti-429 mode)")

    for batch_num, start in enumerate(range(0, total, batch_size), 1):
        batch = tickers[start: start + batch_size]
        logger.info(f"📦 Batch {batch_num}/{total_batches} ({start+1}–{min(start+batch_size, total)}/{total})")

        for ticker in batch:
            df = fetch_daily(ticker)
            if df is not None:
                valid += 1
                results[ticker] = (df, df)  # pakai daily untuk keduanya
            else:
                results[ticker] = (None, None)
            time.sleep(2.0)  # 2 detik per ticker = ~20 req/menit, jauh di bawah limit Yahoo

        if start + batch_size < total:
            logger.info(f"  ⏳ Jeda {sleep_between_batches}s...")
            time.sleep(sleep_between_batches)

    logger.info(f"✅ Done: {valid}/{total} tickers berhasil")
    return results

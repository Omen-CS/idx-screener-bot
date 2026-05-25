import logging
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

_intraday_cache: Dict[str, Tuple[datetime, pd.DataFrame]] = {}
_daily_cache: Dict[str, Tuple[datetime, pd.DataFrame]] = {}

INTRADAY_TTL = 300
DAILY_TTL    = 3600


def _cache_fresh(ts: datetime, ttl: int) -> bool:
    return (datetime.now() - ts).total_seconds() < ttl


def clear_cache() -> None:
    global _intraday_cache, _daily_cache
    _intraday_cache.clear()
    _daily_cache.clear()
    logger.info("Market data cache cleared")


def _flatten(df: pd.DataFrame) -> Optional[pd.DataFrame]:
    if df is None or df.empty:
        return None

    if isinstance(df.columns, pd.MultiIndex):
        df = df.copy()
        df.columns = [str(c[0]).strip() for c in df.columns]

    col_map = {}
    for c in df.columns:
        lc = c.lower().strip()
        if lc == "open":           col_map[c] = "Open"
        elif lc == "high":         col_map[c] = "High"
        elif lc == "low":          col_map[c] = "Low"
        elif lc in ("close", "adj close", "adjclose"): col_map[c] = "Close"
        elif lc == "volume":       col_map[c] = "Volume"
    df = df.rename(columns=col_map)

    required = {"Open", "High", "Low", "Close", "Volume"}
    if not required.issubset(df.columns):
        return None

    df = df[list(required)].copy()
    df = df.dropna(subset=["Close"], how="all")
    df = df.ffill().dropna(subset=["Open", "High", "Low", "Close"])
    df["Volume"] = pd.to_numeric(df["Volume"], errors="coerce").fillna(0).clip(lower=0)

    return df if not df.empty else None


def _download_bulk(tickers: List[str], interval: str, period: str) -> Dict[str, pd.DataFrame]:
    """
    Download banyak ticker sekaligus dengan yf.download().
    Jauh lebih efisien dan mengurangi jumlah request ke Yahoo → hindari 429.
    """
    results = {}
    if not tickers:
        return results

    try:
        raw = yf.download(
            tickers,
            period=period,
            interval=interval,
            auto_adjust=True,
            progress=False,
            group_by="ticker",
        )

        if raw.empty:
            return results

        # Kalau cuma 1 ticker, yfinance tidak pakai MultiIndex ticker level
        if len(tickers) == 1:
            df = _flatten(raw)
            if df is not None:
                results[tickers[0]] = df
            return results

        # Banyak ticker → MultiIndex: (field, ticker)
        for ticker in tickers:
            try:
                if ticker not in raw.columns.get_level_values(1):
                    continue
                df_ticker = raw.xs(ticker, axis=1, level=1)
                df = _flatten(df_ticker)
                if df is not None and not df.empty:
                    results[ticker] = df
            except Exception as e:
                logger.debug(f"  Slice error {ticker}: {e}")

    except Exception as e:
        logger.warning(f"Bulk download error [{interval}/{period}]: {e}")

    return results


def fetch_batch(
    tickers: List[str],
    interval: str = "5m",
    batch_size: int = 50,        # bulk download jauh lebih efisien
    sleep_between_batches: float = 3.0,  # jeda cukup supaya tidak 429
) -> Dict[str, Tuple[Optional[pd.DataFrame], Optional[pd.DataFrame]]]:
    """
    Fetch intraday + daily untuk semua ticker.

    Pakai bulk download (banyak ticker per request) bukan satu-satu.
    Ini drastis mengurangi jumlah HTTP request → hindari rate limit 429.
    """
    results: Dict[str, Tuple[Optional[pd.DataFrame], Optional[pd.DataFrame]]] = {}
    total = len(tickers)
    total_batches = (total + batch_size - 1) // batch_size
    valid = 0

    logger.info(f"🚀 Bulk fetch: {total} tickers, {total_batches} batches of {batch_size}")

    for batch_num, start in enumerate(range(0, total, batch_size), 1):
        batch = tickers[start: start + batch_size]
        logger.info(f"📦 Batch {batch_num}/{total_batches} ({len(batch)} tickers)")

        # Download intraday — coba 1d dulu, fallback 5d
        intraday_data = _download_bulk(batch, interval, "1d")
        if not intraday_data:
            logger.info(f"  1d kosong, coba 5d...")
            time.sleep(1)
            intraday_data = _download_bulk(batch, interval, "5d")

        # Filter hanya hari terakhir untuk intraday
        for ticker, df in intraday_data.items():
            if hasattr(df.index, "date") and not df.empty:
                try:
                    last_date = df.index[-1].date()
                    df_day = df[df.index.date == last_date]
                    if len(df_day) >= 2:
                        intraday_data[ticker] = df_day
                except Exception:
                    pass

        time.sleep(1.5)  # jeda antara intraday dan daily request

        # Download daily
        daily_data = _download_bulk(batch, "1d", "30d")
        if not daily_data:
            time.sleep(1)
            daily_data = _download_bulk(batch, "1d", "60d")

        # Gabungkan hasil
        for ticker in batch:
            df_i = intraday_data.get(ticker)
            df_d = daily_data.get(ticker)
            results[ticker] = (df_i, df_d)
            if df_i is not None:
                valid += 1
                # Cache
                _intraday_cache[f"{ticker}_{interval}"] = (datetime.now(), df_i)
            if df_d is not None:
                _daily_cache[f"{ticker}_daily"] = (datetime.now(), df_d)

        # Jeda antar batch supaya tidak kena 429 lagi
        if start + batch_size < total:
            logger.info(f"  Jeda {sleep_between_batches}s...")
            time.sleep(sleep_between_batches)

    logger.info(f"✅ Fetch complete: {valid}/{total} ticker punya intraday valid")
    return results


def fetch_intraday(ticker: str, interval: str = "5m") -> Optional[pd.DataFrame]:
    cache_key = f"{ticker}_{interval}"
    if cache_key in _intraday_cache:
        ts, df = _intraday_cache[cache_key]
        if _cache_fresh(ts, INTRADAY_TTL):
            return df
    # Single ticker fallback
    data = _download_bulk([ticker], interval, "1d")
    if not data:
        data = _download_bulk([ticker], interval, "5d")
    df = data.get(ticker)
    if df is not None:
        _intraday_cache[cache_key] = (datetime.now(), df)
    return df


def fetch_daily(ticker: str) -> Optional[pd.DataFrame]:
    cache_key = f"{ticker}_daily"
    if cache_key in _daily_cache:
        ts, df = _daily_cache[cache_key]
        if _cache_fresh(ts, DAILY_TTL):
            return df
    data = _download_bulk([ticker], "1d", "30d")
    df = data.get(ticker)
    if df is not None:
        _daily_cache[cache_key] = (datetime.now(), df)
    return df

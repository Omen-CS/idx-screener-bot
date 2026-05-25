import logging
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------
_intraday_cache: Dict[str, Tuple[datetime, pd.DataFrame]] = {}
_daily_cache: Dict[str, Tuple[datetime, pd.DataFrame]] = {}

INTRADAY_TTL = 300   # 5 menit
DAILY_TTL    = 3600  # 60 menit


def _cache_fresh(ts: datetime, ttl: int) -> bool:
    return (datetime.now() - ts).total_seconds() < ttl


def clear_cache() -> None:
    global _intraday_cache, _daily_cache
    _intraday_cache.clear()
    _daily_cache.clear()
    logger.info("Market data cache cleared")


# ---------------------------------------------------------------------------
# Normalise kolom — handle MultiIndex yfinance >= 0.2.31
# ---------------------------------------------------------------------------
def _flatten(df: pd.DataFrame) -> Optional[pd.DataFrame]:
    """
    yfinance >= 0.2.31 selalu return MultiIndex columns bahkan untuk 1 ticker:
        level-0 = nama field  (Close, Open, …)
        level-1 = simbol      (BBCA.JK, …)

    Fungsi ini flatten ke nama biasa + normalise Title Case.
    Return None kalau kolom OHLCV tidak lengkap / frame kosong.
    """
    if df is None or df.empty:
        return None

    # Flatten MultiIndex
    if isinstance(df.columns, pd.MultiIndex):
        df = df.copy()
        df.columns = [str(c[0]).strip() for c in df.columns]

    # Normalise ke Title Case
    col_map: Dict[str, str] = {}
    for c in df.columns:
        lc = c.lower().strip()
        if lc == "open":
            col_map[c] = "Open"
        elif lc == "high":
            col_map[c] = "High"
        elif lc == "low":
            col_map[c] = "Low"
        elif lc in ("close", "adj close", "adjclose"):
            col_map[c] = "Close"
        elif lc == "volume":
            col_map[c] = "Volume"
    df = df.rename(columns=col_map)

    required = {"Open", "High", "Low", "Close", "Volume"}
    if not required.issubset(df.columns):
        return None

    df = df[list(required)].copy()
    df = df.dropna(subset=["Close"], how="all")
    df = df.ffill()
    df = df.dropna(subset=["Open", "High", "Low", "Close"])
    df["Volume"] = (
        pd.to_numeric(df["Volume"], errors="coerce")
        .fillna(0).clip(lower=0).astype(float)
    )

    return df if not df.empty else None


# ---------------------------------------------------------------------------
# Download satu ticker — coba beberapa period
# ---------------------------------------------------------------------------
def _download(ticker: str, interval: str, periods: List[str]) -> Optional[pd.DataFrame]:
    """
    Download data satu ticker, coba tiap period sampai dapat data valid.
    Kenapa ticker-by-ticker? Lebih reliable daripada bulk download di yfinance.
    """
    for period in periods:
        try:
            raw = yf.download(
                ticker,
                period=period,
                interval=interval,
                auto_adjust=True,
                progress=False,
                show_errors=False,
            )
            df = _flatten(raw)
            if df is not None and len(df) >= 2:
                logger.debug(f"  {ticker} [{interval}/{period}]: {len(df)} bars OK")
                return df
        except Exception as e:
            logger.debug(f"  {ticker} [{interval}/{period}] error: {e}")

    return None


# ---------------------------------------------------------------------------
# fetch_intraday — return bar hari terakhir trading
# ---------------------------------------------------------------------------
def fetch_intraday(ticker: str, interval: str = "5m") -> Optional[pd.DataFrame]:
    """
    Ambil data intraday (5m atau 15m) untuk hari trading terakhir.
    Fallback dari period='1d' ke '5d' supaya tetap dapat data
    saat weekend atau hari libur.
    """
    cache_key = f"{ticker}_{interval}"
    if cache_key in _intraday_cache:
        ts, df = _intraday_cache[cache_key]
        if _cache_fresh(ts, INTRADAY_TTL):
            return df

    df = _download(ticker, interval, periods=["1d", "5d"])

    if df is not None:
        df = df.sort_index()
        # Ambil hanya hari terakhir yang ada di data
        if hasattr(df.index, "date"):
            try:
                last_date = df.index[-1].date()
                df_day = df[df.index.date == last_date]
                if len(df_day) >= 2:
                    df = df_day
            except Exception:
                pass

        if df.empty or len(df) < 2:
            df = None

    if df is not None:
        _intraday_cache[cache_key] = (datetime.now(), df)

    return df


# ---------------------------------------------------------------------------
# fetch_daily — return ~30 hari data harian
# ---------------------------------------------------------------------------
def fetch_daily(ticker: str) -> Optional[pd.DataFrame]:
    """Ambil data harian 30 hari terakhir."""
    cache_key = f"{ticker}_daily"
    if cache_key in _daily_cache:
        ts, df = _daily_cache[cache_key]
        if _cache_fresh(ts, DAILY_TTL):
            return df

    df = _download(ticker, "1d", periods=["30d", "60d"])

    if df is not None:
        _daily_cache[cache_key] = (datetime.now(), df)

    return df


# ---------------------------------------------------------------------------
# fetch_batch — main entry point dari scanner
# ---------------------------------------------------------------------------
def fetch_batch(
    tickers: List[str],
    interval: str = "5m",
    batch_size: int = 15,
    sleep_between_batches: float = 1.5,
) -> Dict[str, Tuple[Optional[pd.DataFrame], Optional[pd.DataFrame]]]:
    """
    Fetch intraday + daily untuk semua ticker, diproses per batch.
    Sleep antar batch untuk hindari rate limit Yahoo Finance.

    Kenapa yfinance bukan Stooq?
    - Stooq di-block di Railway (egress allowlist)
    - yfinance pakai Yahoo CDN (Akamai/Fastly) yang tidak di-block Railway
    - Data yfinance punya interval 5m/15m yang dibutuhkan screener BPJS/BSJP
      (Stooq hanya punya data daily, tidak ada intraday)
    """
    results: Dict[str, Tuple[Optional[pd.DataFrame], Optional[pd.DataFrame]]] = {}
    total = len(tickers)
    valid_intraday = 0
    total_batches = (total + batch_size - 1) // batch_size

    logger.info(f"🚀 yfinance ENGINE: Fetching {total} tickers (batch {batch_size})")

    for batch_num, batch_start in enumerate(range(0, total, batch_size), 1):
        batch = tickers[batch_start: batch_start + batch_size]
        logger.info(
            f"📦 Batch {batch_num}/{total_batches} "
            f"(ticker {batch_start + 1}–{min(batch_start + batch_size, total)}/{total})"
        )

        for ticker in batch:
            df_i = fetch_intraday(ticker, interval)
            df_d = fetch_daily(ticker)
            results[ticker] = (df_i, df_d)
            if df_i is not None:
                valid_intraday += 1

        # Sleep antar batch, bukan antar ticker — lebih efisien
        if batch_start + batch_size < total:
            time.sleep(sleep_between_batches)

    logger.info(
        f"✅ Fetch complete: {valid_intraday}/{total} ticker punya data intraday valid"
    )
    return results

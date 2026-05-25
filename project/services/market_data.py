import logging
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple
import pandas as pd
import yfinance as yf
import requests

logger = logging.getLogger(__name__)

# Setup custom session dengan User-Agent Browser agar tidak dicurigai sebagai bot scraper
custom_session = requests.Session()
custom_session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
})

try:
    from config import settings
except ImportError:
    class DummySettings:
        INTRADAY_PERIOD = "5d"
        DAILY_PERIOD = "3mo"
        TICKER_BATCH_SIZE = 15  # Diperkecil sedikit agar tidak memicu rate-limit
        BATCH_SLEEP_SECONDS = 1.5
    settings = DummySettings()

_intraday_cache: Dict[str, Tuple[datetime, pd.DataFrame]] = {}
_daily_cache: Dict[str, Tuple[datetime, pd.DataFrame]] = {}

def clear_cache():
    global _intraday_cache, _daily_cache
    _intraday_cache.clear()
    _daily_cache.clear()
    logger.info("Market data cache cleared")

def fetch_batch(
    tickers: List[str],
    interval: str = "5m",
    batch_size: int = None,
    sleep_between_batches: float = None,
) -> Dict[str, Tuple[Optional[pd.DataFrame], Optional[pd.DataFrame]]]:
    """
    Sistem Fetcher super aman dengan Custom Session & Strict Timeouts.
    Menghindari bot nge-hang di Railway akibat blocking request dari Yahoo Finance.
    """
    if batch_size is None:
        batch_size = getattr(settings, 'TICKER_BATCH_SIZE', 15)
    if sleep_between_batches is None:
        sleep_between_batches = getattr(settings, 'BATCH_SLEEP_SECONDS', 1.5)

    results: Dict[str, Tuple[Optional[pd.DataFrame], Optional[pd.DataFrame]]] = {}
    total = len(tickers)

    logger.info(f"🚀 ULTRA SAFE FETCH: Memulai scan {total} ticker (.JK)")
    clear_cache()

    for batch_start in range(0, total, batch_size):
        batch = tickers[batch_start: batch_start + batch_size]
        batch_num = (batch_start // batch_size) + 1
        total_batches = (total + batch_size - 1) // batch_size

        logger.info(f"📦 Memproses Batch {batch_num}/{total_batches} dengan Session Khusus...")

        # Ambil data per ticker secara aman dengan timeout ketat
        for ticker in batch:
            try:
                # Panggil fungsi download dengan custom session dan timeout 3 detik
                df_in = yf.download(
                    ticker,
                    period=getattr(settings, 'INTRADAY_PERIOD', '5d'),
                    interval=interval,
                    auto_adjust=True,
                    progress=False,
                    threads=False,
                    session=custom_session,
                    timeout=3.0  # 🔥 KUNCI UTAMA: Jika 3 detik gak respon, langsung putus! Gak bakal bikin Railway nge-lag.
                )
                
                df_da = yf.download(
                    ticker,
                    period=getattr(settings, 'DAILY_PERIOD', '3mo'),
                    interval="1d",
                    auto_adjust=True,
                    progress=False,
                    threads=False,
                    session=custom_session,
                    timeout=3.0  # 🔥 KUNCI UTAMA: Batasi waktu tunggu data harian
                )

                # Bersihkan kolom MultiIndex jika ada
                if df_in is not None and isinstance(df_in.columns, pd.MultiIndex):
                    df_in.columns = df_in.columns.get_level_values(0)
                if df_da is not None and isinstance(df_da.columns, pd.MultiIndex):
                    df_da.columns = df_da.columns.get_level_values(0)

                required = {"Open", "High", "Low", "Close", "Volume"}
                valid_in = df_in is not None and not df_in.empty and required.issubset(df_in.columns)
                valid_da = df_da is not None and not df_da.empty and required.issubset(df_da.columns)

                if valid_in and valid_da:
                    df_in = df_in.dropna(subset=["Open", "High", "Low", "Close"])
                    df_da = df_da.dropna(subset=["Open", "High", "Low", "Close"])
                    results[ticker] = (df_in, df_da)
                else:
                    results[ticker] = (None, None)

            except Exception as single_err:
                # Jika timeout atau error, langsung skip tanpa ampun demi keselamatan container Railway
                logger.debug(f"⏩ Ticker {ticker} dilewati karena timeout/error: {single_err}")
                results[ticker] = (None, None)

            # Jeda super pendek antar ticker dalam batch agar server Yahoo gak kaget
            time.sleep(0.2)

        # Jeda antar batch besar
        if batch_start + batch_size < total:
            logger.info(f"😴 Mengistirahatkan koneksi selama {sleep_between_batches} detik...")
            time.sleep(sleep_between_batches)

    valid_count = sum(1 for v in results.values() if v[0] is not None and v[1] is not None)
    logger.info(f"✅ [SCAN SELESAI] Sukses mengamankan {valid_count}/{total} data saham IDX.")
    return results

def fetch_intraday(ticker: str, interval: str = "5m") -> Optional[pd.DataFrame]:
    if ticker in _intraday_cache:
        return _intraday_cache[ticker][1]
    return None

def fetch_daily(ticker: str) -> Optional[pd.DataFrame]:
    if ticker in _daily_cache:
        return _daily_cache[ticker][1]
    return None

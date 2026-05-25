import logging
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple
import pandas as pd
import yfinance as yf
import requests

logger = logging.getLogger(__name__)

# Setup session tiruan browser agar aman
custom_session = requests.Session()
custom_session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
})

try:
    from config import settings
except ImportError:
    class DummySettings:
        DAILY_PERIOD = "3mo"
        TICKER_BATCH_SIZE = 30  # Menggunakan data harian bisa batch lebih besar
        BATCH_SLEEP_SECONDS = 1.0
    settings = DummySettings()

# Cache untuk data daily
_daily_cache: Dict[str, Tuple[datetime, pd.DataFrame]] = {}

def clear_cache():
    global _daily_cache
    _daily_cache.clear()
    logger.info("Market data cache cleared")

def fetch_batch(
    tickers: List[str],
    interval: str = "1d",  # 🔥 DIUBAH KE DAILY
    batch_size: int = None,
    sleep_between_batches: float = None,
) -> Dict[str, Tuple[Optional[pd.DataFrame], Optional[pd.DataFrame]]]:
    """
    Fetcher versi murni Daily (1d) untuk menghindari blokir IP Yahoo Finance di Railway.
    Mengembalikan tuple (df_daily, df_daily) agar kompatibel dengan logic bot lama lu.
    """
    if batch_size is None:
        batch_size = getattr(settings, 'TICKER_BATCH_SIZE', 30)
    if sleep_between_batches is None:
        sleep_between_batches = getattr(settings, 'BATCH_SLEEP_SECONDS', 1.0)

    results: Dict[str, Tuple[Optional[pd.DataFrame], Optional[pd.DataFrame]]] = {}
    total = len(tickers)

    logger.info(f"🚀 PURE DAILY FETCH: Memulai scan harian untuk {total} ticker (.JK)")
    clear_cache()

    for batch_start in range(0, total, batch_size):
        batch = tickers[batch_start: batch_start + batch_size]
        batch_num = (batch_start // batch_size) + 1
        total_batches = (total + batch_size - 1) // batch_size

        logger.info(f"📦 Memproses Batch Harian {batch_num}/{total_batches} ({len(batch)} ticker)...")

        try:
            # Download langsung data harian secara batch (Yahoo sangat toleran dengan data 1d)
            df_daily_all = yf.download(
                tickers=batch,
                period=getattr(settings, 'DAILY_PERIOD', '3mo'),
                interval="1d",
                group_by="ticker",
                auto_adjust=True,
                progress=False,
                threads=False,
                session=custom_session,
                timeout=5.0
            )
        except Exception as e:
            logger.error(f"💥 Gagal mendownload batch harian {batch_num}: {e}")
            df_daily_all = None

        # Ekstraksi data harian per ticker
        for ticker in batch:
            df_da = None
            if df_daily_all is not None and not df_daily_all.empty:
                try:
                    if len(batch) == 1:
                        df_da = df_daily_all.copy()
                    elif ticker in df_daily_all.columns.get_level_values(0):
                        df_da = df_daily_all[ticker].copy()
                    
                    if df_da is not None and not df_da.empty:
                        df_da = df_da.dropna(subset=["Open", "High", "Low", "Close"])
                except Exception:
                    df_da = None

            required = {"Open", "High", "Low", "Close", "Volume"}
            if df_da is not None and not df_da.empty and required.issubset(df_da.columns):
                _daily_cache[ticker] = (datetime.now(), df_da)
                # 🔥 Trik: Masukkan df_da ke slot intraday & daily agar file scanner.py lu gak error/patah rumus
                results[ticker] = (df_da, df_da)
            else:
                results[ticker] = (None, None)

        # Jeda tipis antar batch
        if batch_start + batch_size < total:
            time.sleep(sleep_between_batches)

    valid_count = sum(1 for v in results.values() if v[0] is not None)
    logger.info(f"✅ [SCAN SELESAI] Sukses mendapatkan {valid_count}/{total} data saham IDX.")
    return results

def fetch_intraday(ticker: str, interval: str = "1d") -> Optional[pd.DataFrame]:
    """Fallback pembantu jika modul lain memanggil data menitan"""
    if ticker in _daily_cache:
        return _daily_cache[ticker][1]
    return None

def fetch_daily(ticker: str) -> Optional[pd.DataFrame]:
    """Mengambil data harian dari cache"""
    if ticker in _daily_cache:
        return _daily_cache[ticker][1]
    return None

import logging
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple
import pandas as pd
import yfinance as yf

# Ambil konfigurasi logger dan settings aplikasi lu
logger = logging.getLogger(__name__)

# Fallback jika di settings lu belum ada variabel ini
try:
    from config import settings
except ImportError:
    # Buat class tiruan jika file settings gagal di-import
    class DummySettings:
        INTRADAY_PERIOD = "5d"
        DAILY_PERIOD = "3mo"
        TICKER_BATCH_SIZE = 20
        BATCH_SLEEP_SECONDS = 2.0
    settings = DummySettings()

# Inisialisasi cache memory
_intraday_cache: Dict[str, Tuple[datetime, pd.DataFrame]] = {}
_daily_cache: Dict[str, Tuple[datetime, pd.DataFrame]] = {}

INTRADAY_CACHE_TTL_SECONDS = 300  # 5 Menit
DAILY_CACHE_TTL_SECONDS = 3600    # 1 Jam

def _is_cache_valid(cached_time: datetime, ttl_seconds: int) -> bool:
    """Memeriksa apakah data di dalam cache masih segar atau sudah kedaluwarsa."""
    return (datetime.now() - cached_time).total_seconds() < ttl_seconds

def clear_cache():
    """Membersihkan seluruh cache data pasar."""
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
    Mendownload data pasar secara massal (Batch) dengan yfinance secara aman.
    Menggunakan threads=False untuk menghindari Connection Pool Full & JSONDecodeError di Railway.
    """
    if batch_size is None:
        batch_size = getattr(settings, 'TICKER_BATCH_SIZE', 20)
    if sleep_between_batches is None:
        sleep_between_batches = getattr(settings, 'BATCH_SLEEP_SECONDS', 2.0)

    results: Dict[str, Tuple[Optional[pd.DataFrame], Optional[pd.DataFrame]]] = {}
    total = len(tickers)

    logger.info(f"🚀 NATIVE BATCH: Memulai scan {total} ticker (Ukuran Batch: {batch_size})")

    # Paksa bersihkan cache setiap kali scan baru dimulai agar data selalu fresh
    clear_cache()

    for batch_start in range(0, total, batch_size):
        batch = tickers[batch_start: batch_start + batch_size]
        batch_num = (batch_start // batch_size) + 1
        total_batches = (total + batch_size - 1) // batch_size

        logger.info(f"📦 Memproses Batch {batch_num}/{total_batches} ({len(batch)} ticker)...")

        df_intraday_all = None
        df_daily_all = None

        try:
            # 1. Download data Menitan (Intraday) secara massal
            df_intraday_all = yf.download(
                tickers=batch,
                period=getattr(settings, 'INTRADAY_PERIOD', '5d'),
                interval=interval,
                group_by="ticker",
                auto_adjust=True,
                progress=False,
                threads=False,  # 🔥 FIX UTAMA: Cegah tabrakan connection pool
            )

            # 2. Download data Harian (Daily) secara massal
            df_daily_all = yf.download(
                tickers=batch,
                period=getattr(settings, 'DAILY_PERIOD', '3mo'),
                interval="1d",
                group_by="ticker",
                auto_adjust=True,
                progress=False,
                threads=False,  # 🔥 FIX UTAMA: Cegah tabrakan connection pool
            )

        except Exception as batch_err:
            logger.error(f"💥 Kegagalan koneksi pada Batch {batch_num}: {batch_err}")
            # Lanjut ke proses ekstraksi, nanti ticker di batch ini otomatis ditangani fallback

        # 3. Ekstraksi dan Pembersihan Data Per Ticker
        for ticker in batch:
            df_in = None
            df_da = None

            # --- Ekstrak Data Intraday Menitan ---
            if df_intraday_all is not None and not df_intraday_all.empty:
                try:
                    if len(batch) == 1:
                        df_in = df_intraday_all.copy()
                    elif ticker in df_intraday_all.columns.get_level_values(0):
                        df_in = df_intraday_all[ticker].copy()
                    
                    if df_in is not None and not df_in.empty:
                        df_in = df_in.dropna(subset=["Open", "High", "Low", "Close"])
                except Exception:
                    df_in = None

            # --- Ekstrak Data Daily Harian ---
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

            # --- Validasi Struktur Kolom Saham ---
            required = {"Open", "High", "Low", "Close", "Volume"}
            valid_in = df_in is not None and not df_in.empty and required.issubset(df_in.columns)
            valid_da = df_da is not None and not df_da.empty and required.issubset(df_da.columns)

            if valid_in and valid_da:
                # Simpan ke memori cache biar aman jika dipanggil fungsi single sewaktu-waktu
                _intraday_cache[f"{ticker}_{interval}"] = (datetime.now(), df_in)
                _daily_cache[ticker] = (datetime.now(), df_da)
                
                results[ticker] = (df_in, df_da)
            else:
                # Jika batch massal gagal membaca ticker ini, jalankan Single Fallback (Sistem Cadangan)
                logger.warning(f"⚠️ Data {ticker} tidak lengkap di batch massal. Menjalankan Single Fallback...")
                results[ticker] = fetch_single_fallback(ticker, interval)

        # Beri jeda waktu yang cukup antar batch agar IP Railway lu adem di mata Yahoo Finance
        if batch_start + batch_size < total:
            time.sleep(sleep_between_batches)

    # Hitung total saham yang berhasil lolos sensor
    valid_count = sum(1 for v in results.values() if v[0] is not None and v[1] is not None)
    logger.info(f"✅ [DATA FETCH COMPLETE] Berhasil memvalidasi {valid_count} dari {total} ticker.")
    return results

def fetch_single_fallback(ticker: str, interval: str = "5m") -> Tuple[Optional[pd.DataFrame], Optional[pd.DataFrame]]:
    """
    Fungsi cadangan (fallback) untuk mendownload 1 ticker secara mandiri 
    apabila proses batch massal melewatkan data saham ini.
    """
    df_in = None
    df_da = None
    required = {"Open", "High", "Low", "Close", "Volume"}

    try:
        # Download Intraday Tunggal
        df_in = yf.download(
            ticker,
            period=getattr(settings, 'INTRADAY_PERIOD', '5d'),
            interval=interval,
            auto_adjust=True,
            progress=False,
            threads=False
        )
        if df_in is not None and not df_in.empty:
            if isinstance(df_in.columns, pd.MultiIndex):
                df_in.columns = df_in.columns.get_level_values(0)
            df_in = df_in.dropna(subset=["Open", "High", "Low", "Close"])
            if not required.issubset(df_in.columns):
                df_in = None

        # Download Daily Tunggal
        df_da = yf.download(
            ticker,
            period=getattr(settings, 'DAILY_PERIOD', '3mo'),
            interval="1d",
            auto_adjust=True,
            progress=False,
            threads=False
        )
        if df_da is not None and not df_da.empty:
            if isinstance(df_da.columns, pd.MultiIndex):
                df_da.columns = df_da.columns.get_level_values(0)
            df_da = df_da.dropna(subset=["Open", "High", "Low", "Close"])
            if not required.issubset(df_da.columns):
                df_da = None

        if df_in is not None and df_da is not None:
            return df_in, df_da

    except Exception as e:
        logger.error(f"❌ Single Fallback gagal total untuk {ticker}: {e}")
    
    return None, None

def fetch_intraday(ticker: str, interval: str = "5m") -> Optional[pd.DataFrame]:
    """Fungsi pembantu untuk mengambil data intraday tunggal dari cache atau fallback."""
    cache_key = f"{ticker}_{interval}"
    if cache_key in _intraday_cache:
        t, df = _intraday_cache[cache_key]
        if _is_cache_valid(t, INTRADAY_CACHE_TTL_SECONDS):
            return df
    
    df_in, _ = fetch_single_fallback(ticker, interval)
    return df_in

def fetch_daily(ticker: str) -> Optional[pd.DataFrame]:
    """Fungsi pembantu untuk mengambil data daily tunggal dari cache atau fallback."""
    if ticker in _daily_cache:
        t, df = _daily_cache[ticker]
        if _is_cache_valid(t, DAILY_CACHE_TTL_SECONDS):
            return df
            
    _, df_da = fetch_single_fallback(ticker)
    return df_da

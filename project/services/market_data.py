import logging
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple
import pandas as pd
import requests

logger = logging.getLogger(__name__)

# Cache memory untuk menghindari hit API berulang dalam satu siklus scan
_intraday_cache: Dict[str, Tuple[datetime, pd.DataFrame]] = {}
_daily_cache: Dict[str, Tuple[datetime, pd.DataFrame]] = {}

def clear_cache():
    global _intraday_cache, _daily_cache
    _intraday_cache.clear()
    _daily_cache.clear()
    logger.info("Market data cache cleared")

def fetch_ticker_data_native(ticker: str, interval: str, period_range: str) -> Optional[pd.DataFrame]:
    """
    Fungsi core scraper untuk nembak langsung API data chart.
    interval: '5m' atau '1d'
    period_range: '5d' atau '3mo'
    """
    symbol = ticker.replace(".JK", "").upper()
    url = f"https://query1.financeapi.net/v8/finance/chart/{symbol}.JK?range={period_range}&interval={interval}"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=4)
        if response.status_code != 200:
            return None
            
        data = response.json()
        result = data.get("chart", {}).get("result", [])
        if not result or result[0] is None:
            return None
            
        chart_data = result[0]
        timestamps = chart_data.get("timestamp", [])
        indicators = chart_data.get("indicators", {}).get("quote", [{}])[0]
        
        opens = indicators.get("open", [])
        highs = indicators.get("high", [])
        lows = indicators.get("low", [])
        closes = indicators.get("close", [])
        volumes = indicators.get("volume", [])
        
        if not timestamps or not opens:
            return None
            
        # Buat DataFrame
        df = pd.DataFrame({
            "Open": opens,
            "High": highs,
            "Low": lows,
            "Close": closes,
            "Volume": volumes
        }, index=pd.to_datetime([datetime.fromtimestamp(t) for t in timestamps]))
        
        # Bersihkan baris yang NaN
        df = df.dropna(subset=["Open", "High", "Low", "Close"])
        return df
        
    except Exception:
        return None

def fetch_batch(
    tickers: List[str],
    interval: str = "5m",  # 🔥 Default balik ke Menitan (5m) sesuai request lu!
    batch_size: int = 1,
    sleep_between_batches: float = 0.05,
) -> Dict[str, Tuple[Optional[pd.DataFrame], Optional[pd.DataFrame]]]:
    """
    ULTIMATE FETCHER: Mengambil data MENITAN dan HARIAN secara bersamaan 
    lewat direct API hit. Lolos sensor, anti JSONDecodeError, aman di Railway.
    """
    results: Dict[str, Tuple[Optional[pd.DataFrame], Optional[pd.DataFrame]]] = {}
    total = len(tickers)

    logger.info(f"🚀 DUAL-MODE FETCH: Menarik data Menitan ({interval}) & Harian (1d) untuk {total} ticker")
    clear_cache()

    for idx, ticker in enumerate(tickers, 1):
        if idx % 10 == 0 or idx == 1:
            logger.info(f"📦 Progress Scan: Memproses ticker ke-{idx}/{total}...")
            
        # 1. Ambil data Menitan (Intraday)
        df_in = fetch_ticker_data_native(ticker, interval=interval, period_range="5d")
        
        # 2. Ambil data Harian (Daily)
        df_da = fetch_ticker_data_native(ticker, interval="1d", period_range="3mo")
        
        required = {"Open", "High", "Low", "Close", "Volume"}
        
        valid_in = df_in is not None and not df_in.empty and required.issubset(df_in.columns)
        valid_da = df_da is not None and not df_da.empty and required.issubset(df_da.columns)

        if valid_in and valid_da:
            # Simpan ke cache memory lokal
            _intraday_cache[ticker] = (datetime.now(), df_in)
            _daily_cache[ticker] = (datetime.now(), df_da)
            
            # Kembalikan pasangan data utuh (df_intraday, df_daily)
            results[ticker] = (df_in, df_da)
        else:
            results[ticker] = (None, None)
            
        # Jeda super tipis (50ms) biar request-nya smooth dan gak ngeberatin CPU Railway
        time.sleep(sleep_between_batches)

    valid_count = sum(1 for v in results.values() if v[0] is not None and v[1] is not None)
    logger.info(f"✅ [SCAN COMPLETED] Sukses memuat {valid_count}/{total} ticker dengan data Menitan & Harian!")
    return results

def fetch_intraday(ticker: str, interval: str = "5m") -> Optional[pd.DataFrame]:
    if ticker in _intraday_cache:
        return _intraday_cache[ticker][1]
    return fetch_ticker_data_native(ticker, interval=interval, period_range="5d")

def fetch_daily(ticker: str) -> Optional[pd.DataFrame]:
    if ticker in _daily_cache:
        return _daily_cache[ticker][1]
    return fetch_ticker_data_native(ticker, interval="1d", period_range="3mo")

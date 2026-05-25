import logging
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple
import pandas as pd
import requests

logger = logging.getLogger(__name__)

_intraday_cache: Dict[str, Tuple[datetime, pd.DataFrame]] = {}
_daily_cache: Dict[str, Tuple[datetime, pd.DataFrame]] = {}

def clear_cache():
    global _intraday_cache, _daily_cache
    _intraday_cache.clear()
    _daily_cache.clear()
    logger.info("Market data cache cleared")

def fetch_ticker_data_native(ticker: str, interval: str, period_range: str) -> Optional[pd.DataFrame]:
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
        
        if not timestamps or not opens or None in opens[:3]: # Cek jika data kosong atau corrupt
            return None
            
        df = pd.DataFrame({
            "Open": opens,
            "High": highs,
            "Low": lows,
            "Close": closes,
            "Volume": volumes
        }, index=pd.to_datetime([datetime.fromtimestamp(t) for t in timestamps]))
        
        df = df.dropna(subset=["Open", "High", "Low", "Close"])
        return df
        
    except Exception:
        return None

def fetch_batch(
    tickers: List[str],
    interval: str = "5m",
    batch_size: int = 1,
    sleep_between_batches: float = 0.04,
) -> Dict[str, Tuple[Optional[pd.DataFrame], Optional[pd.DataFrame]]]:
    """
    ULTIMATE FETCHER V2: Mengambil data dengan auto-fallback interval 
    jika data 5m IDX sedang kosong di server Yahoo Finance.
    """
    results: Dict[str, Tuple[Optional[pd.DataFrame], Optional[pd.DataFrame]]] = {}
    total = len(tickers)

    logger.info(f"🚀 DUAL-MODE FETCH V2: Memproses {total} ticker (.JK)")
    clear_cache()

    for idx, ticker in enumerate(tickers, 1):
        if idx % 20 == 0 or idx == 1:
            logger.info(f"📦 Progress Scan: Memproses ticker ke-{idx}/{total}...")
            
        # 1. Ambil data Harian (Daily) dulu karena ini paling stabil
        df_da = fetch_ticker_data_native(ticker, interval="1d", period_range="3mo")
        
        # 2. Ambil data Menitan (Intraday)
        df_in = fetch_ticker_data_native(ticker, interval=interval, period_range="5d")
        
        # 🔥 ALTERNATIF JIKA DATA 5M KOSONG: Coba tembak interval 15m atau pakai data harian sebagai penambal
        if df_in is None or df_in.empty:
            df_in = fetch_ticker_data_native(ticker, interval="15m", period_range="5d")
            if df_in is None or df_in.empty:
                df_in = df_da # Fallback terakhir pake data harian biar bot gak zonk
        
        required = {"Open", "High", "Low", "Close", "Volume"}
        valid_in = df_in is not None and not df_in.empty and required.issubset(df_in.columns)
        valid_da = df_da is not None and not df_da.empty and required.issubset(df_da.columns)

        if valid_in and valid_da:
            _intraday_cache[ticker] = (datetime.now(), df_in)
            _daily_cache[ticker] = (datetime.now(), df_da)
            results[ticker] = (df_in, df_da)
        else:
            results[ticker] = (None, None)
            
        time.sleep(sleep_between_batches)

    valid_count = sum(1 for v in results.values() if v[0] is not None and v[1] is not None)
    logger.info(f"✅ [SCAN COMPLETED] Sukses memuat {valid_count}/{total} ticker ke dalam sistem!")
    return results

def fetch_intraday(ticker: str, interval: str = "5m") -> Optional[pd.DataFrame]:
    if ticker in _intraday_cache:
        return _intraday_cache[ticker][1]
    return fetch_ticker_data_native(ticker, interval=interval, period_range="5d")

def fetch_daily(ticker: str) -> Optional[pd.DataFrame]:
    if ticker in _daily_cache:
        return _daily_cache[ticker][1]
    return fetch_ticker_data_native(ticker, interval="1d", period_range="3mo")

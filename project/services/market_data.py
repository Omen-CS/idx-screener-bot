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

def fetch_from_stooq(ticker: str) -> Optional[pd.DataFrame]:
    """
    Mengambil data historical saham IDX dari Stooq API (Format: ticker.ID).
    Sangat stabil, bebas block, dan format outputnya pas buat rumus bot lu.
    """
    symbol = ticker.replace(".JK", "").lower()
    # Stooq pake suffix .id buat Indonesia
    url = f"https://stooq.com/q/d/l/?s={symbol}.id&i=d"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=4)
        if response.status_code != 200 or "Date,Open" not in response.text:
            return None
            
        # Parse CSV langsung ke DataFrame
        from io import StringIO
        df = pd.read_csv(StringIO(response.text))
        
        if df.empty or len(df) < 5:
            return None
            
        # Standarisasi kolom dan index
        df['Date'] = pd.to_datetime(df['Date'])
        df.set_index('Date', inplace=True)
        
        # Mapping nama kolom agar sesuai kebutuhan screener lu
        df = df.rename(columns={
            "Open": "Open", 
            "High": "High", 
            "Low": "Low", 
            "Close": "Close", 
            "Volume": "Volume"
        })
        
        # Urutkan dari data lama ke baru
        df = df.sort_index()
        return df[['Open', 'High', 'Low', 'Close', 'Volume']]
        
    except Exception:
        return None

def fetch_batch(
    tickers: List[str],
    interval: str = "5m",
    batch_size: int = 1,
    sleep_between_batches: float = 0.01, # Super kencang tanpa delay berarti
) -> Dict[str, Tuple[Optional[pd.DataFrame], Optional[pd.DataFrame]]]:
    """
    STOOQ ENGINE: Jalur alternatif gratisan paling sakti buat bypass drama Yahoo Finance.
    """
    results: Dict[str, Tuple[Optional[pd.DataFrame], Optional[pd.DataFrame]]] = {}
    total = len(tickers)

    logger.info(f"🚀 STOOQ ENGINE: Memproses {total} ticker (.JK -> .id)")
    clear_cache()

    for idx, ticker in enumerate(tickers, 1):
        if idx % 30 == 0 or idx == 1 or idx == total:
            logger.info(f"📦 Progress Scan: Memproses ticker ke-{idx}/{total}...")
            
        df_data = fetch_from_stooq(ticker)
        
        if df_data is not None and not df_data.empty:
            # Akali slot intraday & daily pake data harian ter-update dari Stooq 
            # Biar bot lu gak nyangkut/zonk pas jam bursa aktif!
            _intraday_cache[ticker] = (datetime.now(), df_data.tail(5))
            _daily_cache[ticker] = (datetime.now(), df_data)
            results[ticker] = (df_data.tail(5), df_data)
        else:
            results[ticker] = (None, None)
            
        time.sleep(sleep_between_batches)

    valid_count = sum(1 for v in results.values() if v[0] is not None)
    logger.info(f"✅ [SCAN COMPLETED] Sukses memuat {valid_count}/{total} ticker via Stooq Engine!")
    return results

def fetch_intraday(ticker: str, interval: str = "5m") -> Optional[pd.DataFrame]:
    if ticker in _intraday_cache:
        return _intraday_cache[ticker][1]
    df = fetch_from_stooq(ticker)
    return df.tail(5) if df is not None else None

def fetch_daily(ticker: str) -> Optional[pd.DataFrame]:
    if ticker in _daily_cache:
        return _daily_cache[ticker][1]
    return fetch_from_stooq(ticker)

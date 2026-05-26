"""
screener/scanner.py — Daily Mode

Karena data source (Stooq) hanya punya DAILY data,
semua kalkulasi intraday diganti dengan equivalent daily:

  BPJS logic (daily equivalent):
  - Relative volume    → hari ini vs rata2 20 hari
  - Price move         → % change hari ini (Close vs Open)
  - Morning high break → Close > High 3 hari sebelumnya
  - Above VWAP         → Close > EMA10 (proxy VWAP harian)
  - Higher low         → Low hari ini > Low kemarin

  BSJP logic (daily equivalent):
  - Close near high    → Close/High ratio hari ini
  - Strong last hour   → Volume hari ini vs kemarin
  - Resistance break   → Close > High 20 hari terakhir
  - Accumulation       → 3 hari volume naik berturut
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

import pytz

from config import settings
from screener.tickers import get_idx_tickers
from services.market_data import fetch_batch, clear_cache, DATA_MODE

logger = logging.getLogger(__name__)
WIB = pytz.timezone("Asia/Jakarta")


def market_status_msg() -> str:
    now = datetime.now(WIB)
    day = now.strftime("%A")
    t = now.strftime("%H:%M")
    open_ = now.weekday() < 5 and 9 <= now.hour < 16
    status = "OPEN" if open_ else "CLOSED"
    return f"Market {status} ({day} {t} WIB) | Mode: {DATA_MODE.upper()}"


def is_market_open() -> bool:
    now = datetime.now(WIB)
    return now.weekday() < 5 and 9 <= now.hour < 16


@dataclass
class StockCandidate:
    ticker: str
    score: int
    price: float
    mode: str
    signals_triggered: List[str] = field(default_factory=list)
    rel_volume: float = 0.0
    price_change_pct: float = 0.0
    rsi: float = 50.0
    traded_value_idr: float = 0.0


# ---------------------------------------------------------------------------
# Daily-mode indicator helpers
# ---------------------------------------------------------------------------
import numpy as np
import pandas as pd


def _ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def _rsi(series: pd.Series, period: int = 14) -> float:
    if len(series) < period + 1:
        return 50.0
    delta = series.diff()
    gain = delta.clip(lower=0).ewm(com=period-1, min_periods=period).mean()
    loss = (-delta.clip(upper=0)).ewm(com=period-1, min_periods=period).mean()
    rs = gain.iloc[-1] / loss.iloc[-1] if loss.iloc[-1] > 0 else 100
    return float(100 - 100 / (1 + rs))


def _score_daily_bpjs(df: pd.DataFrame) -> tuple:
    """Score sebuah saham untuk BPJS menggunakan daily data."""
    score = 0
    signals = []

    if len(df) < 5:
        return 0, []

    today = df.iloc[-1]
    prev  = df.iloc[-2]

    # --- Relative Volume (+25) ---
    avg_vol = df["Volume"].iloc[-21:-1].mean()
    rel_vol = today["Volume"] / avg_vol if avg_vol > 0 else 1.0
    if rel_vol >= 2.0:
        score += 25
        signals.append("Volume Explosion")

    # --- Price Move dari Open (+25) ---
    if today["Open"] > 0:
        pct = (today["Close"] - today["Open"]) / today["Open"] * 100
    else:
        pct = 0.0

    if 1.0 <= pct <= 10.0:
        score += 25
        signals.append("Morning Breakout")

    # --- Bullish Structure (+20) ---
    bullish_candle = today["Close"] > today["Open"]
    higher_low = today["Low"] > prev["Low"]
    candle_range = today["High"] - today["Low"]
    upper_wick = (today["High"] - max(today["Open"], today["Close"])) / candle_range if candle_range > 0 else 0

    struct_score = 0
    if bullish_candle:   struct_score += 8
    if higher_low:       struct_score += 7
    if upper_wick < 0.4: struct_score += 5
    if struct_score >= 8:
        score += min(struct_score, 20)
        signals.append("Bullish Structure")

    # --- Above EMA20 proxy VWAP (+15) ---
    ema20 = _ema(df["Close"], 20).iloc[-1]
    if today["Close"] > ema20:
        score += 15
        signals.append("Above VWAP")

    # --- Momentum: RSI not overbought + above EMA (+15) ---
    rsi_val = _rsi(df["Close"])
    ema_trend = _ema(df["Close"], 20).iloc[-1] > _ema(df["Close"], 20).iloc[-3]
    if rsi_val < 85 and ema_trend:
        score += 15
        signals.append("Bullish Momentum")

    # Penalty: illiquid (< 500M IDR)
    traded = today["Close"] * today["Volume"]
    if traded < 500_000_000:
        score = max(0, score - 20)

    return min(score, 100), signals


def _score_daily_bsjp(df: pd.DataFrame) -> tuple:
    """Score sebuah saham untuk BSJP menggunakan daily data."""
    score = 0
    signals = []

    if len(df) < 5:
        return 0, []

    today = df.iloc[-1]
    prev3 = df.iloc[-4:-1]

    # --- Close near high (+30) ---
    candle_range = today["High"] - today["Low"]
    close_ratio = (today["Close"] - today["Low"]) / candle_range if candle_range > 0 else 1.0
    upper_wick = (today["High"] - max(today["Open"], today["Close"])) / candle_range if candle_range > 0 else 0

    close_score = 0
    if close_ratio >= 0.85:
        close_score += 20
        signals.append("Strong Close")
    if upper_wick < 0.3:
        close_score += 10
    score += min(close_score, 30)

    # --- Resistance breakout (+25) ---
    resist = df["High"].iloc[-21:-1].max()
    if today["Close"] > resist:
        score += 25
        signals.append("Resistance Breakout")

    # --- Accumulation volume (+20) ---
    avg_vol = df["Volume"].iloc[-21:-1].mean()
    vol_ratio = today["Volume"] / avg_vol if avg_vol > 0 else 1.0
    accum = all(df["Volume"].iloc[-i] >= df["Volume"].iloc[-i-1] for i in range(1, 4))

    accum_score = 0
    if vol_ratio >= 1.3: accum_score += 12
    if accum:
        accum_score += 8
        signals.append("Afternoon Accumulation")
    score += min(accum_score, 20)

    # --- Bullish trend (+15) ---
    ema20 = _ema(df["Close"], 20)
    ema_bull = today["Close"] > ema20.iloc[-1] and ema20.iloc[-1] > ema20.iloc[-3]
    higher_low = today["Low"] > df["Low"].iloc[-2]
    trend_score = 0
    if ema_bull:    trend_score += 8
    if higher_low:  trend_score += 7
    if trend_score >= 8:
        score += min(trend_score, 15)
        signals.append("Bullish Structure")

    # --- Low selling pressure (+10) ---
    no_panic = today["Close"] >= today["Open"]
    if no_panic: score += 10

    # Penalty: illiquid
    if today["Close"] * today["Volume"] < 300_000_000:
        score = max(0, score - 15)

    return min(score, 100), signals


# ---------------------------------------------------------------------------
# Main scan functions
# ---------------------------------------------------------------------------
def run_bpjs_scan(top_n: int = None) -> List[StockCandidate]:
    if top_n is None:
        top_n = settings.TOP_N_RESULTS

    logger.info(f"=== BPJS Scan — {market_status_msg()} ===")
    clear_cache()

    tickers = get_idx_tickers()
    data = fetch_batch(tickers, interval="5m")

    candidates = []
    for ticker, (df_i, df_d) in data.items():
        df = df_d if df_d is not None else df_i
        if df is None or df.empty or len(df) < 5:
            continue

        price = float(df["Close"].iloc[-1])
        if not (settings.MIN_PRICE_IDR <= price <= settings.MAX_PRICE_IDR):
            continue

        score, triggered = _score_daily_bpjs(df)
        if score < settings.MIN_SCORE_THRESHOLD:
            continue

        avg_vol = df["Volume"].iloc[-21:-1].mean()
        rel_vol = float(df["Volume"].iloc[-1] / avg_vol) if avg_vol > 0 else 1.0
        pct = (float(df["Close"].iloc[-1]) - float(df["Open"].iloc[-1])) / float(df["Open"].iloc[-1]) * 100 if float(df["Open"].iloc[-1]) > 0 else 0

        candidates.append(StockCandidate(
            ticker=ticker, score=score, price=price, mode="BPJS",
            signals_triggered=triggered, rel_volume=rel_vol,
            price_change_pct=pct, rsi=_rsi(df["Close"]),
            traded_value_idr=float(df["Close"].iloc[-1] * df["Volume"].iloc[-1]),
        ))

    candidates.sort(key=lambda x: x.score, reverse=True)
    logger.info(f"BPJS: {len(candidates)} kandidat ditemukan")
    return candidates[:top_n]


def run_bsjp_scan(top_n: int = None) -> List[StockCandidate]:
    if top_n is None:
        top_n = settings.TOP_N_RESULTS

    logger.info(f"=== BSJP Scan — {market_status_msg()} ===")
    clear_cache()

    tickers = get_idx_tickers()
    data = fetch_batch(tickers, interval="15m")

    candidates = []
    for ticker, (df_i, df_d) in data.items():
        df = df_d if df_d is not None else df_i
        if df is None or df.empty or len(df) < 5:
            continue

        price = float(df["Close"].iloc[-1])
        if not (settings.MIN_PRICE_IDR <= price <= settings.MAX_PRICE_IDR):
            continue

        score, triggered = _score_daily_bsjp(df)
        if score < settings.MIN_SCORE_THRESHOLD:
            continue

        avg_vol = df["Volume"].iloc[-21:-1].mean()
        rel_vol = float(df["Volume"].iloc[-1] / avg_vol) if avg_vol > 0 else 1.0
        pct = (float(df["Close"].iloc[-1]) - float(df["Open"].iloc[-1])) / float(df["Open"].iloc[-1]) * 100 if float(df["Open"].iloc[-1]) > 0 else 0

        candidates.append(StockCandidate(
            ticker=ticker, score=score, price=price, mode="BSJP",
            signals_triggered=triggered, rel_volume=rel_vol,
            price_change_pct=pct, rsi=_rsi(df["Close"]),
            traded_value_idr=float(df["Close"].iloc[-1] * df["Volume"].iloc[-1]),
        ))

    candidates.sort(key=lambda x: x.score, reverse=True)
    logger.info(f"BSJP: {len(candidates)} kandidat ditemukan")
    return candidates[:top_n]


def run_full_scan(top_n: int = None) -> Dict[str, List[StockCandidate]]:
    return {
        "bpjs": run_bpjs_scan(top_n),
        "bsjp": run_bsjp_scan(top_n),
    }

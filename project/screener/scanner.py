"""
screener/scanner.py — dengan ARA Hunter terintegrasi

ARA (Auto Reject Atas) potential detector otomatis ikut di setiap scan.
Kalau terdeteksi, kandidat dapat label ARA_POTENTIAL = True dan
muncul tanda khusus di alert tanpa perlu command tambahan.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
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
    return f"Market {status} ({day} {t} WIB)"


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
    ara_potential: bool = False        # flag ARA
    ara_score: int = 0                 # score khusus ARA 0-100


# ---------------------------------------------------------------------------
# Helper indicators
# ---------------------------------------------------------------------------

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


def _pct_change(df: pd.DataFrame) -> float:
    """% change Close hari ini vs Close kemarin — sama dengan Stockbit."""
    if len(df) < 2:
        return 0.0
    prev_close = float(df["Close"].iloc[-2])
    curr_close = float(df["Close"].iloc[-1])
    if prev_close <= 0:
        return 0.0
    return (curr_close - prev_close) / prev_close * 100


# ---------------------------------------------------------------------------
# ARA Hunter — detector potensi Auto Reject Atas
# ---------------------------------------------------------------------------

def _detect_ara_potential(df: pd.DataFrame) -> Tuple[bool, int, List[str]]:
    """
    Deteksi saham yang berpotensi ARA keesokan harinya.

    Sinyal yang digunakan:
    1. Volume explosion ekstrem (>5x rata-rata)
    2. Close sangat dekat High (>95% range)
    3. Breakout dari konsolidasi (harga sideways lalu meledak)
    4. Akumulasi diam-diam (volume naik 3+ hari, harga belum banyak gerak)
    5. Candle body besar (>70% dari range)
    6. Momentum acceleration (hari ini lebih kuat dari kemarin)

    Returns:
        (is_ara_potential, ara_score, ara_signals)
    """
    if len(df) < 10:
        return False, 0, []

    ara_score = 0
    ara_signals = []

    today = df.iloc[-1]
    prev  = df.iloc[-2]
    recent = df.tail(10)

    # --- 1. Volume explosion ekstrem (+30) ---
    avg_vol = df["Volume"].iloc[-21:-1].mean()
    rel_vol = float(today["Volume"] / avg_vol) if avg_vol > 0 else 1.0
    if rel_vol >= 5.0:
        ara_score += 30
        ara_signals.append(f"Volume {rel_vol:.1f}x")
    elif rel_vol >= 3.0:
        ara_score += 15

    # --- 2. Close sangat dekat High (+25) ---
    candle_range = float(today["High"] - today["Low"])
    if candle_range > 0:
        close_to_high = (float(today["Close"]) - float(today["Low"])) / candle_range
        if close_to_high >= 0.97:
            ara_score += 25
            ara_signals.append("Close = High")
        elif close_to_high >= 0.90:
            ara_score += 12

    # --- 3. Candle body besar (+15) ---
    if candle_range > 0:
        body = abs(float(today["Close"]) - float(today["Open"]))
        body_ratio = body / candle_range
        if body_ratio >= 0.80:
            ara_score += 15
            ara_signals.append("Candle Kuat")
        elif body_ratio >= 0.65:
            ara_score += 8

    # --- 4. Breakout dari konsolidasi (+20) ---
    # Sideways = range harga 5 hari sebelumnya kecil, hari ini meledak
    prev5_high = df["High"].iloc[-7:-2].max()
    prev5_low  = df["Low"].iloc[-7:-2].min()
    prev5_range_pct = (prev5_high - prev5_low) / prev5_low * 100 if prev5_low > 0 else 0
    pct_today = _pct_change(df)

    if prev5_range_pct < 5.0 and pct_today >= 5.0:
        # Konsolidasi ketat lalu breakout kuat
        ara_score += 20
        ara_signals.append("Breakout Konsolidasi")
    elif prev5_range_pct < 8.0 and pct_today >= 3.0:
        ara_score += 10

    # --- 5. Akumulasi diam-diam (+10) ---
    # Volume naik 3 hari berturut tapi harga naik perlahan
    vol_increasing = all(
        df["Volume"].iloc[-i] >= df["Volume"].iloc[-i-1]
        for i in range(1, 4)
    )
    price_slow = abs(_pct_change(df)) < 3.0  # harga belum banyak gerak
    if vol_increasing and price_slow:
        ara_score += 10
        ara_signals.append("Akumulasi Tersembunyi")

    # --- Threshold: ARA potential kalau score >= 40 ---
    is_ara = ara_score >= 40

    return is_ara, min(ara_score, 100), ara_signals


# ---------------------------------------------------------------------------
# BPJS scoring
# ---------------------------------------------------------------------------

def _score_daily_bpjs(df: pd.DataFrame) -> Tuple[int, List[str]]:
    score = 0
    signals = []

    if len(df) < 5:
        return 0, []

    today = df.iloc[-1]
    prev  = df.iloc[-2]
    pct   = _pct_change(df)

    # Volume Explosion (+25)
    avg_vol = df["Volume"].iloc[-21:-1].mean()
    rel_vol = today["Volume"] / avg_vol if avg_vol > 0 else 1.0
    if rel_vol >= 2.0:
        score += 25
        signals.append("Volume Explosion")

    # Price Move (+25)
    if 1.0 <= pct <= 10.0:
        score += 25
        signals.append("Morning Breakout")

    # Bullish Structure (+20)
    bullish_candle = today["Close"] > prev["Close"]
    higher_low     = today["Low"] > prev["Low"]
    candle_range   = today["High"] - today["Low"]
    upper_wick     = (today["High"] - max(today["Open"], today["Close"])) / candle_range if candle_range > 0 else 0

    struct_score = 0
    if bullish_candle:   struct_score += 8
    if higher_low:       struct_score += 7
    if upper_wick < 0.4: struct_score += 5
    if struct_score >= 8:
        score += min(struct_score, 20)
        signals.append("Bullish Structure")

    # Above EMA20 (+15)
    ema20 = _ema(df["Close"], 20).iloc[-1]
    if today["Close"] > ema20:
        score += 15
        signals.append("Above VWAP")

    # Momentum (+15)
    rsi_val   = _rsi(df["Close"])
    ema_trend = _ema(df["Close"], 20).iloc[-1] > _ema(df["Close"], 20).iloc[-3]
    if rsi_val < 85 and ema_trend:
        score += 15
        signals.append("Bullish Momentum")

    if today["Close"] * today["Volume"] < 500_000_000:
        score = max(0, score - 20)

    return min(score, 100), signals


# ---------------------------------------------------------------------------
# BSJP scoring
# ---------------------------------------------------------------------------

def _score_daily_bsjp(df: pd.DataFrame) -> Tuple[int, List[str]]:
    score = 0
    signals = []

    if len(df) < 5:
        return 0, []

    today = df.iloc[-1]
    prev  = df.iloc[-2]

    # Close near high (+30)
    candle_range = today["High"] - today["Low"]
    close_ratio  = (today["Close"] - today["Low"]) / candle_range if candle_range > 0 else 1.0
    upper_wick   = (today["High"] - max(today["Open"], today["Close"])) / candle_range if candle_range > 0 else 0

    close_score = 0
    if close_ratio >= 0.85:
        close_score += 20
        signals.append("Strong Close")
    if upper_wick < 0.3:
        close_score += 10
    score += min(close_score, 30)

    # Resistance breakout (+25)
    resist = df["High"].iloc[-21:-1].max()
    if today["Close"] > resist:
        score += 25
        signals.append("Resistance Breakout")

    # Accumulation volume (+20)
    avg_vol   = df["Volume"].iloc[-21:-1].mean()
    vol_ratio = today["Volume"] / avg_vol if avg_vol > 0 else 1.0
    accum     = all(df["Volume"].iloc[-i] >= df["Volume"].iloc[-i-1] for i in range(1, 4))

    accum_score = 0
    if vol_ratio >= 1.3: accum_score += 12
    if accum:
        accum_score += 8
        signals.append("Afternoon Accumulation")
    score += min(accum_score, 20)

    # Bullish trend (+15)
    ema20     = _ema(df["Close"], 20)
    ema_bull  = today["Close"] > ema20.iloc[-1] and ema20.iloc[-1] > ema20.iloc[-3]
    higher_low = today["Low"] > prev["Low"]

    trend_score = 0
    if ema_bull:    trend_score += 8
    if higher_low:  trend_score += 7
    if trend_score >= 8:
        score += min(trend_score, 15)
        signals.append("Bullish Structure")

    # Low selling pressure (+10)
    if today["Close"] >= prev["Close"]:
        score += 10

    if today["Close"] * today["Volume"] < 300_000_000:
        score = max(0, score - 15)

    return min(score, 100), signals


# ---------------------------------------------------------------------------
# Main scan functions
# ---------------------------------------------------------------------------

def _build_candidate(ticker, df, mode, score, triggered) -> StockCandidate:
    """Build StockCandidate dengan ARA detection terintegrasi."""
    avg_vol = df["Volume"].iloc[-21:-1].mean()
    rel_vol = float(df["Volume"].iloc[-1] / avg_vol) if avg_vol > 0 else 1.0
    pct     = _pct_change(df)

    # Deteksi ARA potential
    is_ara, ara_score, ara_signals = _detect_ara_potential(df)

    # Kalau ARA terdeteksi, tambahkan ke signals
    if is_ara:
        for s in ara_signals:
            if s not in triggered:
                triggered.append(s)

    return StockCandidate(
        ticker=ticker,
        score=score,
        price=float(df["Close"].iloc[-1]),
        mode=mode,
        signals_triggered=triggered,
        rel_volume=rel_vol,
        price_change_pct=pct,
        rsi=_rsi(df["Close"]),
        traded_value_idr=float(df["Close"].iloc[-1] * df["Volume"].iloc[-1]),
        ara_potential=is_ara,
        ara_score=ara_score,
    )


def run_bpjs_scan(top_n: int = None) -> List[StockCandidate]:
    if top_n is None:
        top_n = settings.TOP_N_RESULTS

    logger.info(f"=== BPJS Scan — {market_status_msg()} ===")
    clear_cache()

    tickers = get_idx_tickers()
    data    = fetch_batch(tickers, interval="5m")

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

        candidates.append(_build_candidate(ticker, df, "BPJS", score, triggered))

    # Sort: ARA potential naik ke atas, lalu by score
    candidates.sort(key=lambda x: (x.ara_potential, x.score), reverse=True)
    logger.info(f"BPJS: {len(candidates)} kandidat, {sum(1 for c in candidates if c.ara_potential)} ARA potential")
    return candidates[:top_n]


def run_bsjp_scan(top_n: int = None) -> List[StockCandidate]:
    if top_n is None:
        top_n = settings.TOP_N_RESULTS

    logger.info(f"=== BSJP Scan — {market_status_msg()} ===")
    clear_cache()

    tickers = get_idx_tickers()
    data    = fetch_batch(tickers, interval="15m")

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

        candidates.append(_build_candidate(ticker, df, "BSJP", score, triggered))

    candidates.sort(key=lambda x: (x.ara_potential, x.score), reverse=True)
    logger.info(f"BSJP: {len(candidates)} kandidat, {sum(1 for c in candidates if c.ara_potential)} ARA potential")
    return candidates[:top_n]


def run_full_scan(top_n: int = None) -> Dict[str, List[StockCandidate]]:
    return {
        "bpjs": run_bpjs_scan(top_n),
        "bsjp": run_bsjp_scan(top_n),
    }


def run_combined_top_scan(top_n: int = None):
    return run_bpjs_scan(top_n), run_bsjp_scan(top_n)

"""
screener/scanner.py — Logic Upgrade v2

Implementasi:
1. Fresh Breakout Detection
2. Anti-Endgame Filter
3. Continuation Probability
4. Accumulation Detection
5. Quality Momentum
6. Label: HIGH CONTINUATION / POSSIBLE EXHAUSTION / ONE DAY SPIKE
7. ARA Hunter terintegrasi
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
    open_ = now.weekday() < 5 and 9 <= now.hour < 16
    return f"Market {'OPEN' if open_ else 'CLOSED'} ({now.strftime('%A %H:%M')} WIB)"


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
    ara_potential: bool = False
    ara_score: int = 0
    continuation_label: str = ""   # HIGH CONTINUATION / POSSIBLE EXHAUSTION / ONE DAY SPIKE


# ---------------------------------------------------------------------------
# Indicators
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
    prev = float(df["Close"].iloc[-2])
    curr = float(df["Close"].iloc[-1])
    return (curr - prev) / prev * 100 if prev > 0 else 0.0


def _upper_wick_ratio(row: pd.Series) -> float:
    rng = float(row["High"]) - float(row["Low"])
    if rng <= 0:
        return 0.0
    wick = float(row["High"]) - max(float(row["Open"]), float(row["Close"]))
    return max(0.0, wick / rng)


def _lower_wick_ratio(row: pd.Series) -> float:
    rng = float(row["High"]) - float(row["Low"])
    if rng <= 0:
        return 0.0
    wick = min(float(row["Open"]), float(row["Close"])) - float(row["Low"])
    return max(0.0, wick / rng)


def _body_ratio(row: pd.Series) -> float:
    rng = float(row["High"]) - float(row["Low"])
    if rng <= 0:
        return 0.0
    return abs(float(row["Close"]) - float(row["Open"])) / rng


def _close_ratio(row: pd.Series) -> float:
    """Posisi close dalam range candle (0=low, 1=high)."""
    rng = float(row["High"]) - float(row["Low"])
    if rng <= 0:
        return 1.0
    return (float(row["Close"]) - float(row["Low"])) / rng


# ---------------------------------------------------------------------------
# 1. Fresh Breakout Detection
# ---------------------------------------------------------------------------

def _detect_fresh_breakout(df: pd.DataFrame) -> Tuple[bool, int]:
    """
    Deteksi breakout baru dari konsolidasi.
    Bukan yang sudah naik berhari-hari.

    Returns: (is_fresh_breakout, bonus_score)
    """
    if len(df) < 10:
        return False, 0

    today = df.iloc[-1]

    # Cek konsolidasi 5-15 hari sebelumnya
    lookback = min(15, len(df) - 1)
    prior = df.iloc[-(lookback+1):-1]

    # Range konsolidasi: High-Low dalam persentase
    consol_high = float(prior["High"].max())
    consol_low  = float(prior["Low"].min())
    if consol_low <= 0:
        return False, 0

    consol_range_pct = (consol_high - consol_low) / consol_low * 100

    # Konsolidasi ketat = range < 15%
    is_consolidating = consol_range_pct < 15.0

    # Hari ini breakout di atas resistance konsolidasi
    breaking_out = float(today["Close"]) > consol_high

    # Volume naik bertahap (bukan spike tiba-tiba)
    avg_vol_prior = float(prior["Volume"].mean())
    today_vol = float(today["Volume"])
    vol_ratio = today_vol / avg_vol_prior if avg_vol_prior > 0 else 1.0
    gradual_vol = 1.5 <= vol_ratio <= 8.0  # tidak terlalu explosif = lebih organik

    # Candle rapih: body ratio > 0.6, upper wick < 0.3
    clean_candle = _body_ratio(today) > 0.6 and _upper_wick_ratio(today) < 0.3

    if is_consolidating and breaking_out:
        score = 0
        if gradual_vol:   score += 15
        if clean_candle:  score += 10
        score += 5  # base fresh breakout
        return True, score

    return False, 0


# ---------------------------------------------------------------------------
# 2. Anti-Endgame Filter
# ---------------------------------------------------------------------------

def _anti_endgame_penalty(df: pd.DataFrame) -> Tuple[int, List[str]]:
    """
    Deteksi tanda-tanda saham sudah di endgame (distribusi bandar).
    Return: (penalty_score, warning_labels)
    """
    if len(df) < 5:
        return 0, []

    penalty = 0
    warnings = []

    today    = df.iloc[-1]
    prev     = df.iloc[-2]
    prev2    = df.iloc[-3] if len(df) >= 3 else prev

    # Total naik 2 hari terakhir
    if len(df) >= 3:
        two_day_gain = (float(today["Close"]) - float(prev2["Close"])) / float(prev2["Close"]) * 100
        if two_day_gain > 20.0:
            penalty += 30
            warnings.append("ENDGAME: Naik >20% 2 hari")
        elif two_day_gain > 15.0:
            penalty += 15
            warnings.append("CAUTION: Naik >15% 2 hari")

    # RSI overbought
    rsi_val = _rsi(df["Close"])
    if rsi_val > 80:
        penalty += 25
        warnings.append("RSI Overbought")
    elif rsi_val > 70:
        penalty += 10

    # Jauh dari EMA20
    ema20_val = float(_ema(df["Close"], 20).iloc[-1])
    if ema20_val > 0:
        dist_from_ema = (float(today["Close"]) - ema20_val) / ema20_val * 100
        if dist_from_ema > 20.0:
            penalty += 20
            warnings.append("Terlalu Jauh EMA20")
        elif dist_from_ema > 12.0:
            penalty += 10

    # Upper wick panjang = selling pressure
    uw = _upper_wick_ratio(today)
    if uw > 0.5:
        penalty += 20
        warnings.append("Upper Wick Panjang")
    elif uw > 0.35:
        penalty += 10

    # Volume climax: hari ini volume jauh di atas rata-rata DAN harga tidak lanjut
    avg_vol = float(df["Volume"].iloc[-21:-1].mean())
    today_vol = float(today["Volume"])
    if avg_vol > 0:
        vol_ratio = today_vol / avg_vol
        price_gain = _pct_change(df)
        if vol_ratio > 10 and price_gain < 3.0:
            penalty += 15
            warnings.append("Volume Climax")

    return penalty, warnings


# ---------------------------------------------------------------------------
# 3. Continuation Probability
# ---------------------------------------------------------------------------

def _continuation_probability(df: pd.DataFrame) -> Tuple[str, int]:
    """
    Hitung peluang lanjut berdasarkan kombinasi sinyal.

    Returns:
        label: "HIGH CONTINUATION" / "POSSIBLE EXHAUSTION" / "ONE DAY SPIKE"
        bonus: bonus/penalty score
    """
    if len(df) < 5:
        return "", 0

    today = df.iloc[-1]
    score = 0

    # Positif
    if _close_ratio(today) >= 0.85:    score += 20  # close near high
    if _upper_wick_ratio(today) < 0.2: score += 15  # no upper wick
    if _body_ratio(today) > 0.7:       score += 10  # strong body

    # Volume sustain (tidak turun di akhir)
    avg_vol = float(df["Volume"].iloc[-21:-1].mean())
    if avg_vol > 0 and float(today["Volume"]) >= avg_vol * 1.2:
        score += 10

    # Higher low
    if len(df) >= 3 and float(today["Low"]) > float(df.iloc[-2]["Low"]):
        score += 10

    # EMA trending up
    ema20 = _ema(df["Close"], 20)
    if len(ema20) >= 3 and float(ema20.iloc[-1]) > float(ema20.iloc[-3]):
        score += 10

    # Negatif
    if _upper_wick_ratio(today) > 0.4:  score -= 20  # wick panjang
    if _close_ratio(today) < 0.5:       score -= 15  # close lemah
    if _body_ratio(today) < 0.3:        score -= 10  # candle kecil/doji

    # Volume spike absurd tapi harga tidak naik banyak
    pct = _pct_change(df)
    avg_vol2 = float(df["Volume"].iloc[-21:-1].mean())
    if avg_vol2 > 0:
        vol_ratio = float(today["Volume"]) / avg_vol2
        if vol_ratio > 15 and pct < 5.0:
            score -= 25  # dump signal

    # Label berdasarkan total score
    if score >= 40:
        return "HIGH CONTINUATION", 10
    elif score >= 15:
        return "", 0
    elif score >= -10:
        return "POSSIBLE EXHAUSTION", -10
    else:
        return "ONE DAY SPIKE", -20


# ---------------------------------------------------------------------------
# 4. Accumulation Detection
# ---------------------------------------------------------------------------

def _detect_accumulation(df: pd.DataFrame) -> Tuple[bool, int]:
    """
    Deteksi akumulasi diam-diam:
    - Volume besar tapi harga belum lari
    - Candle kecil tapi value gede
    - Sideways rapi
    - Lower wick panjang (support kuat)
    """
    if len(df) < 7:
        return False, 0

    today  = df.iloc[-1]
    recent = df.tail(5)

    score = 0

    # Volume naik tapi harga sideways
    avg_vol = float(df["Volume"].iloc[-21:-1].mean())
    recent_vol_avg = float(recent["Volume"].mean())
    vol_increasing = recent_vol_avg > avg_vol * 1.3

    price_range = float(recent["High"].max()) - float(recent["Low"].min())
    price_base  = float(recent["Low"].min())
    sideways    = (price_range / price_base * 100) < 8.0 if price_base > 0 else False

    if vol_increasing and sideways:
        score += 20

    # Lower wick panjang = ada yang beli di bawah (support kuat)
    lw = _lower_wick_ratio(today)
    if lw > 0.4:
        score += 15
    elif lw > 0.25:
        score += 8

    # Value gede tapi candle kecil (distribusi vs akumulasi)
    traded_val = float(today["Close"]) * float(today["Volume"])
    body = _body_ratio(today)
    if traded_val > 5_000_000_000 and body < 0.4:
        score += 10  # nilai besar tapi candle kecil = akumulasi pelan

    # Volume naik 3 hari berturut-turut
    vol_trend_up = all(
        float(df["Volume"].iloc[-i]) >= float(df["Volume"].iloc[-i-1])
        for i in range(1, 4)
    )
    if vol_trend_up:
        score += 10

    return score >= 25, score


# ---------------------------------------------------------------------------
# 5. Quality Momentum Check
# ---------------------------------------------------------------------------

def _quality_momentum(df: pd.DataFrame) -> Tuple[bool, int]:
    """
    Momentum berkualitas:
    - Naik stabil (bukan spike liar)
    - Higher low
    - Candle rapih
    - Breakout sehat
    """
    if len(df) < 5:
        return False, 0

    score = 0
    today    = df.iloc[-1]
    prev     = df.iloc[-2]

    # Higher low (trend sehat)
    if float(today["Low"]) > float(prev["Low"]):
        score += 15

    # Candle rapih: body > 0.5, wick tidak ekstrem
    if _body_ratio(today) > 0.5:
        score += 10
    if _upper_wick_ratio(today) < 0.25:
        score += 10

    # Naik stabil: tidak spike lebih dari 15% dalam 1 hari
    pct = _pct_change(df)
    if 1.0 <= pct <= 12.0:
        score += 10
    elif pct > 15.0:
        score -= 15  # spike terlalu liar

    # EMA alignment: harga di atas EMA20
    ema20 = float(_ema(df["Close"], 20).iloc[-1])
    if float(today["Close"]) > ema20:
        score += 10

    return score >= 30, score


# ---------------------------------------------------------------------------
# ARA Hunter
# ---------------------------------------------------------------------------

def _detect_ara_potential(df: pd.DataFrame) -> Tuple[bool, int, List[str]]:
    if len(df) < 10:
        return False, 0, []

    ara_score = 0
    ara_signals = []
    today = df.iloc[-1]

    avg_vol = float(df["Volume"].iloc[-21:-1].mean())
    rel_vol = float(today["Volume"]) / avg_vol if avg_vol > 0 else 1.0

    # Volume explosion ekstrem
    if rel_vol >= 5.0:
        ara_score += 30
        ara_signals.append(f"Volume {rel_vol:.1f}x")
    elif rel_vol >= 3.0:
        ara_score += 15

    # Close sangat dekat High
    cr = _close_ratio(today)
    if cr >= 0.97:
        ara_score += 25
        ara_signals.append("Close = High")
    elif cr >= 0.90:
        ara_score += 12

    # Candle body besar
    if _body_ratio(today) >= 0.80:
        ara_score += 15
        ara_signals.append("Candle Kuat")
    elif _body_ratio(today) >= 0.65:
        ara_score += 8

    # Breakout dari konsolidasi
    lookback = min(10, len(df) - 1)
    prior = df.iloc[-(lookback+1):-1]
    consol_high = float(prior["High"].max())
    consol_low  = float(prior["Low"].min())
    if consol_low > 0:
        consol_range_pct = (consol_high - consol_low) / consol_low * 100
        pct = _pct_change(df)
        if consol_range_pct < 5.0 and pct >= 5.0:
            ara_score += 20
            ara_signals.append("Breakout Konsolidasi")
        elif consol_range_pct < 8.0 and pct >= 3.0:
            ara_score += 10

    # Akumulasi diam-diam
    vol_increasing = all(
        float(df["Volume"].iloc[-i]) >= float(df["Volume"].iloc[-i-1])
        for i in range(1, 4)
    )
    if vol_increasing and abs(_pct_change(df)) < 3.0:
        ara_score += 10
        ara_signals.append("Akumulasi Tersembunyi")

    return ara_score >= 40, min(ara_score, 100), ara_signals


# ---------------------------------------------------------------------------
# BPJS Scoring — Full Logic
# ---------------------------------------------------------------------------

def _score_bpjs_full(df: pd.DataFrame) -> Tuple[int, List[str]]:
    """BPJS scoring dengan semua logic upgrade."""
    if len(df) < 5:
        return 0, []

    score = 0
    signals = []
    today = df.iloc[-1]
    prev  = df.iloc[-2]
    pct   = _pct_change(df)

    avg_vol   = float(df["Volume"].iloc[-21:-1].mean())
    today_vol = float(today["Volume"])
    rel_vol   = today_vol / avg_vol if avg_vol > 0 else 1.0

    # --- Base BPJS signals ---

    # Volume (max 25)
    if rel_vol >= 2.0:
        score += 25
        signals.append("Volume Explosion")
    elif rel_vol >= 1.5:
        score += 12

    # Price move (max 20)
    if 1.0 <= pct <= 10.0:
        score += 20
        signals.append("Morning Breakout")
    elif pct > 10.0:
        score += 5  # masih kasih tapi kecil, mungkin endgame

    # Bullish structure (max 15)
    struct = 0
    if float(today["Close"]) > float(prev["Close"]): struct += 5
    if float(today["Low"]) > float(prev["Low"]):      struct += 5
    if _upper_wick_ratio(today) < 0.3:                struct += 3
    if _body_ratio(today) > 0.6:                      struct += 2
    if struct >= 8:
        score += struct
        signals.append("Bullish Structure")

    # Above EMA20 (max 10)
    ema20 = float(_ema(df["Close"], 20).iloc[-1])
    if float(today["Close"]) > ema20:
        score += 10
        signals.append("Above VWAP")

    # RSI tidak overbought (max 10)
    rsi_val = _rsi(df["Close"])
    ema_trend = float(_ema(df["Close"], 20).iloc[-1]) > float(_ema(df["Close"], 20).iloc[-3])
    if rsi_val < 75 and ema_trend:
        score += 10
        signals.append("Bullish Momentum")

    # --- Upgrade: Fresh Breakout (+max 30) ---
    is_fresh, fresh_score = _detect_fresh_breakout(df)
    if is_fresh:
        score += fresh_score
        signals.append("Fresh Breakout")

    # --- Upgrade: Accumulation (+max 20) ---
    is_accum, accum_score = _detect_accumulation(df)
    if is_accum:
        score += min(accum_score // 2, 20)
        signals.append("Akumulasi Tersembunyi")

    # --- Upgrade: Quality Momentum (+max 15) ---
    is_quality, quality_score = _quality_momentum(df)
    if is_quality:
        score += min(quality_score // 3, 15)

    # --- Anti-Endgame Penalty ---
    penalty, warn_labels = _anti_endgame_penalty(df)
    score = max(0, score - penalty)

    # Liquidity penalty
    traded_val = float(today["Close"]) * today_vol
    if traded_val < 500_000_000:
        score = max(0, score - 20)

    return min(score, 100), signals


# ---------------------------------------------------------------------------
# BSJP Scoring — Full Logic
# ---------------------------------------------------------------------------

def _score_bsjp_full(df: pd.DataFrame) -> Tuple[int, List[str]]:
    """BSJP scoring dengan semua logic upgrade."""
    if len(df) < 5:
        return 0, []

    score = 0
    signals = []
    today = df.iloc[-1]
    prev  = df.iloc[-2]

    avg_vol   = float(df["Volume"].iloc[-21:-1].mean())
    today_vol = float(today["Volume"])
    vol_ratio = today_vol / avg_vol if avg_vol > 0 else 1.0

    # --- Strong Close (max 30) ---
    cr = _close_ratio(today)
    if cr >= 0.88:
        score += 20
        signals.append("Strong Close")
    elif cr >= 0.75:
        score += 10

    uw = _upper_wick_ratio(today)
    if uw < 0.2:
        score += 10  # clean close
    elif uw < 0.3:
        score += 5

    # --- Resistance Breakout (max 20) ---
    resist = float(df["High"].iloc[-21:-1].max())
    if float(today["Close"]) > resist:
        score += 20
        signals.append("Resistance Breakout")

    # --- Accumulation (max 20) ---
    is_accum, accum_score = _detect_accumulation(df)
    if is_accum:
        score += min(accum_score // 2, 20)
        signals.append("Afternoon Accumulation")
    elif vol_ratio >= 1.3:
        score += 10

    # --- Bullish Trend (max 15) ---
    ema20 = _ema(df["Close"], 20)
    ema_bull = float(ema20.iloc[-1]) > float(ema20.iloc[-3]) if len(ema20) >= 3 else False
    higher_low = float(today["Low"]) > float(prev["Low"])

    trend = 0
    if ema_bull:    trend += 8
    if higher_low:  trend += 7
    if trend >= 8:
        score += min(trend, 15)
        signals.append("Bullish Structure")

    # --- No Panic Selling (max 10) ---
    if float(today["Close"]) >= float(prev["Close"]):
        score += 5
    if uw < 0.25:
        score += 5

    # --- Fresh Breakout bonus ---
    is_fresh, fresh_score = _detect_fresh_breakout(df)
    if is_fresh:
        score += min(fresh_score, 15)
        if "Fresh Breakout" not in signals:
            signals.append("Fresh Breakout")

    # --- Anti-Endgame ---
    penalty, _ = _anti_endgame_penalty(df)
    score = max(0, score - penalty)

    traded_val = float(today["Close"]) * today_vol
    if traded_val < 300_000_000:
        score = max(0, score - 15)

    return min(score, 100), signals


# ---------------------------------------------------------------------------
# Build candidate
# ---------------------------------------------------------------------------

def _build_candidate(ticker: str, df: pd.DataFrame, mode: str,
                     score: int, triggered: List[str]) -> StockCandidate:

    avg_vol = float(df["Volume"].iloc[-21:-1].mean())
    rel_vol = float(df["Volume"].iloc[-1]) / avg_vol if avg_vol > 0 else 1.0
    pct     = _pct_change(df)

    # Continuation label
    cont_label, cont_bonus = _continuation_probability(df)
    score = max(0, min(100, score + cont_bonus))

    # ARA detection
    is_ara, ara_score, ara_signals = _detect_ara_potential(df)
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
        continuation_label=cont_label,
    )


# ---------------------------------------------------------------------------
# Scan functions
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

        score, triggered = _score_bpjs_full(df)
        if score < settings.MIN_SCORE_THRESHOLD:
            continue

        candidates.append(_build_candidate(ticker, df, "BPJS", score, triggered))

    # Sort: ARA dulu, lalu HIGH CONTINUATION, lalu by score
    def sort_key(c):
        cont_priority = {"HIGH CONTINUATION": 2, "": 1, "POSSIBLE EXHAUSTION": 0, "ONE DAY SPIKE": -1}
        return (c.ara_potential, cont_priority.get(c.continuation_label, 0), c.score)

    candidates.sort(key=sort_key, reverse=True)
    ara_count  = sum(1 for c in candidates if c.ara_potential)
    high_count = sum(1 for c in candidates if c.continuation_label == "HIGH CONTINUATION")
    logger.info(f"BPJS: {len(candidates)} kandidat | {ara_count} ARA | {high_count} HIGH CONT")
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

        score, triggered = _score_bsjp_full(df)
        if score < settings.MIN_SCORE_THRESHOLD:
            continue

        candidates.append(_build_candidate(ticker, df, "BSJP", score, triggered))

    def sort_key(c):
        cont_priority = {"HIGH CONTINUATION": 2, "": 1, "POSSIBLE EXHAUSTION": 0, "ONE DAY SPIKE": -1}
        return (c.ara_potential, cont_priority.get(c.continuation_label, 0), c.score)

    candidates.sort(key=sort_key, reverse=True)
    ara_count  = sum(1 for c in candidates if c.ara_potential)
    high_count = sum(1 for c in candidates if c.continuation_label == "HIGH CONTINUATION")
    logger.info(f"BSJP: {len(candidates)} kandidat | {ara_count} ARA | {high_count} HIGH CONT")
    return candidates[:top_n]


def run_full_scan(top_n: int = None) -> Dict[str, List[StockCandidate]]:
    return {
        "bpjs": run_bpjs_scan(top_n),
        "bsjp": run_bsjp_scan(top_n),
    }


def run_combined_top_scan(top_n: int = None):
    return run_bpjs_scan(top_n), run_bsjp_scan(top_n)

"""
screener/scanner.py — Filter Gacor v3

Philosophy: QUALITY OVER QUANTITY
- Semua logic digabung jadi satu filter pipeline
- Saham harus lolos SEMUA gate sebelum masuk output
- Max 5 kandidat, tapi semuanya high quality
- Tidak ada false positive dari saham turun/illiquid

Pipeline:
1. GATE 1: Liquidity & Basic (value, harga, move)
2. GATE 2: Structure Quality (candle, wick, close ratio)
3. GATE 3: Volume Quality (volume real, bukan fake spike)
4. GATE 4: Trend Alignment (EMA, higher low)
5. GATE 5: Anti-Endgame (bukan yang sudah telat)
6. GATE 6: Fresh Setup (breakout baru / akumulasi)
7. SCORE: Ranking dari yang lolos semua gate
8. LABEL: HIGH CONTINUATION / ARA POTENTIAL
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
    continuation_label: str = ""


# ---------------------------------------------------------------------------
# Core Indicators
# ---------------------------------------------------------------------------

def _ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def _rsi(series: pd.Series, period: int = 14) -> float:
    if len(series) < period + 1:
        return 50.0
    delta = series.diff()
    gain  = delta.clip(lower=0).ewm(com=period-1, min_periods=period).mean()
    loss  = (-delta.clip(upper=0)).ewm(com=period-1, min_periods=period).mean()
    rs    = gain.iloc[-1] / loss.iloc[-1] if loss.iloc[-1] > 0 else 100
    return float(100 - 100 / (1 + rs))


def _pct_change(df: pd.DataFrame) -> float:
    if len(df) < 2:
        return 0.0
    prev = float(df["Close"].iloc[-2])
    curr = float(df["Close"].iloc[-1])
    return (curr - prev) / prev * 100 if prev > 0 else 0.0


def _upper_wick(row: pd.Series) -> float:
    rng = float(row["High"]) - float(row["Low"])
    if rng <= 0: return 0.0
    wick = float(row["High"]) - max(float(row["Open"]), float(row["Close"]))
    return max(0.0, wick / rng)


def _lower_wick(row: pd.Series) -> float:
    rng = float(row["High"]) - float(row["Low"])
    if rng <= 0: return 0.0
    wick = min(float(row["Open"]), float(row["Close"])) - float(row["Low"])
    return max(0.0, wick / rng)


def _body(row: pd.Series) -> float:
    rng = float(row["High"]) - float(row["Low"])
    if rng <= 0: return 0.0
    return abs(float(row["Close"]) - float(row["Open"])) / rng


def _close_ratio(row: pd.Series) -> float:
    rng = float(row["High"]) - float(row["Low"])
    if rng <= 0: return 1.0
    return (float(row["Close"]) - float(row["Low"])) / rng


# ---------------------------------------------------------------------------
# THE FILTER PIPELINE
# ---------------------------------------------------------------------------

def _run_filter_pipeline_bpjs(df: pd.DataFrame) -> Tuple[bool, str]:
    """
    BPJS Filter Pipeline — semua gate harus lolos.

    Returns:
        (passed, reject_reason)
    """
    if len(df) < 10:
        return False, "data tidak cukup"

    today   = df.iloc[-1]
    prev    = df.iloc[-2]
    avg_vol = float(df["Volume"].iloc[-21:-1].mean())
    today_vol = float(today["Volume"])
    rel_vol   = today_vol / avg_vol if avg_vol > 0 else 1.0
    traded_val = float(today["Close"]) * today_vol
    pct        = _pct_change(df)
    rsi_val    = _rsi(df["Close"])
    ema20_val  = float(_ema(df["Close"], 20).iloc[-1])
    ema20_prev = float(_ema(df["Close"], 20).iloc[-3]) if len(df) >= 3 else ema20_val

    # ═══════════════════════════════════════════════
    # GATE 1: LIQUIDITY & BASIC
    # ═══════════════════════════════════════════════
    if traded_val < 2_000_000_000:
        return False, f"value terlalu kecil ({traded_val/1e9:.1f}B)"

    if float(today["Close"]) < settings.MIN_PRICE_IDR:
        return False, "harga terlalu rendah"

    # BPJS: harga HARUS naik
    if pct <= 0:
        return False, f"harga turun ({pct:.1f}%)"

    # ═══════════════════════════════════════════════
    # GATE 2: CANDLE STRUCTURE QUALITY
    # ═══════════════════════════════════════════════
    # Upper wick tidak boleh terlalu panjang
    uw = _upper_wick(today)
    if uw > 0.40:
        return False, f"upper wick terlalu panjang ({uw:.0%})"

    # Close harus di atas tengah range (tidak lemah)
    cr = _close_ratio(today)
    if cr < 0.60:
        return False, f"close terlalu lemah ({cr:.0%})"

    # Candle tidak boleh doji ekstrem
    if _body(today) < 0.20:
        return False, "candle doji (tidak ada arah)"

    # ═══════════════════════════════════════════════
    # GATE 3: VOLUME QUALITY
    # ═══════════════════════════════════════════════
    # Volume harus di atas rata-rata
    if rel_vol < 1.5:
        return False, f"volume lemah ({rel_vol:.1f}x)"

    # Volume terlalu absurd tanpa move = fake/manipulasi
    if rel_vol > 20.0 and pct < 2.0:
        return False, f"volume spike tidak wajar ({rel_vol:.0f}x tapi move {pct:.1f}%)"

    # ═══════════════════════════════════════════════
    # GATE 4: TREND ALIGNMENT
    # ═══════════════════════════════════════════════
    # Harga harus di atas EMA20
    if float(today["Close"]) < ema20_val:
        return False, "di bawah EMA20"

    # EMA20 harus trending up (tidak sideways/down)
    if ema20_val < ema20_prev * 0.998:
        return False, "EMA20 downtrend"

    # Harus ada higher low (struktur bullish)
    if float(today["Low"]) < float(prev["Low"]) * 0.98:
        return False, "lower low (struktur lemah)"

    # ═══════════════════════════════════════════════
    # GATE 5: ANTI-ENDGAME
    # ═══════════════════════════════════════════════
    # RSI tidak boleh overbought
    if rsi_val > 80:
        return False, f"RSI overbought ({rsi_val:.0f})"

    # Tidak boleh naik terlalu tinggi dalam 2 hari (kemungkinan endgame)
    if len(df) >= 3:
        two_day_gain = (float(today["Close"]) - float(df.iloc[-3]["Close"])) / float(df.iloc[-3]["Close"]) * 100
        if two_day_gain > 25.0:
            return False, f"sudah naik {two_day_gain:.0f}% dalam 2 hari (endgame risk)"

    # Tidak terlalu jauh dari EMA20 (distribusi zone)
    if ema20_val > 0:
        dist = (float(today["Close"]) - ema20_val) / ema20_val * 100
        if dist > 25.0:
            return False, f"terlalu jauh dari EMA20 ({dist:.0f}%)"

    # ═══════════════════════════════════════════════
    # GATE 6: FRESH SETUP CHECK
    # ═══════════════════════════════════════════════
    # Minimal salah satu: fresh breakout ATAU accumulation ATAU momentum baru
    lookback = min(10, len(df) - 1)
    prior    = df.iloc[-(lookback+1):-1]
    consol_high = float(prior["High"].max())
    consol_low  = float(prior["Low"].min())

    is_breakout   = float(today["Close"]) > consol_high
    is_accum      = False
    is_new_momentum = pct >= 1.5 and rel_vol >= 2.0

    # Cek accumulation: volume naik 3 hari tapi harga masih wajar
    if len(df) >= 4:
        vol_trend = all(
            float(df["Volume"].iloc[-i]) >= float(df["Volume"].iloc[-i-1])
            for i in range(1, 4)
        )
        price_range_pct = (consol_high - consol_low) / consol_low * 100 if consol_low > 0 else 99
        is_accum = vol_trend and price_range_pct < 12.0

    if not (is_breakout or is_accum or is_new_momentum):
        return False, "tidak ada fresh setup (breakout/akumulasi/momentum baru)"

    return True, ""


def _run_filter_pipeline_bsjp(df: pd.DataFrame) -> Tuple[bool, str]:
    """
    BSJP Filter Pipeline — fokus overnight continuation.
    """
    if len(df) < 10:
        return False, "data tidak cukup"

    today    = df.iloc[-1]
    prev     = df.iloc[-2]
    avg_vol  = float(df["Volume"].iloc[-21:-1].mean())
    today_vol = float(today["Volume"])
    rel_vol   = today_vol / avg_vol if avg_vol > 0 else 1.0
    traded_val = float(today["Close"]) * today_vol
    pct        = _pct_change(df)
    rsi_val    = _rsi(df["Close"])
    ema20_val  = float(_ema(df["Close"], 20).iloc[-1])
    ema20_prev = float(_ema(df["Close"], 20).iloc[-3]) if len(df) >= 3 else ema20_val

    # GATE 1: LIQUIDITY
    if traded_val < 1_000_000_000:
        return False, f"value terlalu kecil ({traded_val/1e9:.2f}B)"

    if float(today["Close"]) < settings.MIN_PRICE_IDR:
        return False, "harga terlalu rendah"

    # GATE 2: STRONG CLOSE — ini yang paling penting untuk BSJP
    cr = _close_ratio(today)
    if cr < 0.80:
        return False, f"close lemah, tidak dekat high ({cr:.0%})"

    uw = _upper_wick(today)
    if uw > 0.30:
        return False, f"upper wick panjang ({uw:.0%}) — ada selling pressure"

    # GATE 3: VOLUME QUALITY
    if rel_vol < 1.3:
        return False, f"volume tidak cukup ({rel_vol:.1f}x)"

    # GATE 4: TREND ALIGNMENT
    if float(today["Close"]) < ema20_val:
        return False, "di bawah EMA20"

    if ema20_val < ema20_prev * 0.997:
        return False, "EMA20 downtrend"

    # GATE 5: ANTI-ENDGAME
    if rsi_val > 78:
        return False, f"RSI terlalu tinggi ({rsi_val:.0f})"

    if len(df) >= 3:
        two_day_gain = (float(today["Close"]) - float(df.iloc[-3]["Close"])) / float(df.iloc[-3]["Close"]) * 100
        if two_day_gain > 20.0:
            return False, f"naik {two_day_gain:.0f}% dalam 2 hari"

    if ema20_val > 0:
        dist = (float(today["Close"]) - ema20_val) / ema20_val * 100
        if dist > 20.0:
            return False, f"terlalu jauh EMA20 ({dist:.0f}%)"

    # GATE 6: OVERNIGHT SETUP
    # Harus ada sinyal lanjut besok
    higher_low      = float(today["Low"]) >= float(prev["Low"])
    no_panic        = float(today["Close"]) >= float(prev["Close"])
    vol_accumulating = rel_vol >= 1.5

    # Resistance breakout
    resist = float(df["High"].iloc[-21:-1].max())
    breaking_resist  = float(today["Close"]) > resist

    if not (higher_low and (no_panic or breaking_resist or vol_accumulating)):
        return False, "tidak ada setup overnight yang kuat"

    return True, ""


# ---------------------------------------------------------------------------
# Scoring (untuk ranking setelah lolos semua gate)
# ---------------------------------------------------------------------------

def _score_passed(df: pd.DataFrame, mode: str) -> Tuple[int, List[str]]:
    """
    Scoring untuk saham yang sudah lolos semua filter.
    Ini untuk ranking, bukan untuk filter.
    """
    score = 50  # base score karena sudah lolos semua gate
    signals = []

    today    = df.iloc[-1]
    avg_vol  = float(df["Volume"].iloc[-21:-1].mean())
    rel_vol  = float(today["Volume"]) / avg_vol if avg_vol > 0 else 1.0
    pct      = _pct_change(df)
    rsi_val  = _rsi(df["Close"])
    ema20    = _ema(df["Close"], 20)
    cr       = _close_ratio(today)
    uw       = _upper_wick(today)

    # Volume quality
    if rel_vol >= 5.0:
        score += 15
        signals.append(f"Volume {rel_vol:.1f}x")
    elif rel_vol >= 3.0:
        score += 10
        signals.append(f"Volume {rel_vol:.1f}x")
    elif rel_vol >= 2.0:
        score += 5
        signals.append(f"Volume {rel_vol:.1f}x")

    # Price move
    if mode == "BPJS":
        if 3.0 <= pct <= 8.0:
            score += 10
            signals.append(f"Move {pct:.1f}%")
        elif pct > 1.0:
            score += 5
            signals.append(f"Move {pct:.1f}%")

    # Close quality
    if cr >= 0.90:
        score += 10
        signals.append("Close Near High")
    elif cr >= 0.75:
        score += 5

    # Clean candle
    if uw < 0.15:
        score += 10
        signals.append("Clean Candle")
    elif uw < 0.25:
        score += 5

    # EMA alignment
    if len(ema20) >= 5:
        ema_slope = (float(ema20.iloc[-1]) - float(ema20.iloc[-5])) / float(ema20.iloc[-5]) * 100
        if ema_slope > 1.0:
            score += 5
            signals.append("EMA Trending Up")

    # Fresh breakout
    lookback    = min(10, len(df) - 1)
    prior       = df.iloc[-(lookback+1):-1]
    consol_high = float(prior["High"].max())
    if float(today["Close"]) > consol_high:
        score += 10
        signals.append("Fresh Breakout")

    # RSI sweet spot (tidak overbought, tidak oversold)
    if 45 <= rsi_val <= 65:
        score += 5
        signals.append("RSI Ideal")
    elif 65 < rsi_val <= 75:
        score += 2

    # Higher low
    if len(df) >= 2 and float(today["Low"]) > float(df.iloc[-2]["Low"]):
        score += 5
        signals.append("Higher Low")

    # Resistance breakout (BSJP bonus)
    if mode == "BSJP":
        resist = float(df["High"].iloc[-21:-1].max())
        if float(today["Close"]) > resist:
            score += 10
            signals.append("Resistance Breakout")

    return min(score, 100), signals


# ---------------------------------------------------------------------------
# ARA Hunter
# ---------------------------------------------------------------------------

def _detect_ara(df: pd.DataFrame) -> Tuple[bool, int, List[str]]:
    if len(df) < 5:
        return False, 0, []

    today    = df.iloc[-1]
    avg_vol  = float(df["Volume"].iloc[-21:-1].mean())
    rel_vol  = float(today["Volume"]) / avg_vol if avg_vol > 0 else 1.0
    ara_score = 0
    ara_sigs  = []

    if rel_vol >= 5.0:
        ara_score += 30
        ara_sigs.append(f"Vol {rel_vol:.1f}x")
    elif rel_vol >= 3.0:
        ara_score += 15

    if _close_ratio(today) >= 0.97:
        ara_score += 25
        ara_sigs.append("Close = High")
    elif _close_ratio(today) >= 0.92:
        ara_score += 12

    if _body(today) >= 0.80:
        ara_score += 15
        ara_sigs.append("Candle Kuat")
    elif _body(today) >= 0.65:
        ara_score += 8

    lookback    = min(10, len(df) - 1)
    prior       = df.iloc[-(lookback+1):-1]
    consol_high = float(prior["High"].max())
    consol_low  = float(prior["Low"].min())
    if consol_low > 0:
        consol_range = (consol_high - consol_low) / consol_low * 100
        pct = _pct_change(df)
        if consol_range < 5.0 and pct >= 5.0:
            ara_score += 20
            ara_sigs.append("Breakout Konsolidasi Ketat")
        elif consol_range < 8.0 and pct >= 3.0:
            ara_score += 10

    if len(df) >= 4:
        vol_trend = all(
            float(df["Volume"].iloc[-i]) >= float(df["Volume"].iloc[-i-1])
            for i in range(1, 4)
        )
        if vol_trend and abs(_pct_change(df)) < 3.0:
            ara_score += 10
            ara_sigs.append("Akumulasi Tersembunyi")

    return ara_score >= 45, min(ara_score, 100), ara_sigs


# ---------------------------------------------------------------------------
# Continuation Label
# ---------------------------------------------------------------------------

def _get_continuation_label(df: pd.DataFrame) -> str:
    if len(df) < 3:
        return ""

    today = df.iloc[-1]
    score = 0

    if _close_ratio(today) >= 0.88: score += 20
    if _upper_wick(today) < 0.15:   score += 15
    if _body(today) > 0.70:         score += 10

    avg_vol = float(df["Volume"].iloc[-21:-1].mean())
    if avg_vol > 0 and float(today["Volume"]) >= avg_vol * 1.5:
        score += 10

    ema20 = _ema(df["Close"], 20)
    if len(ema20) >= 3 and float(ema20.iloc[-1]) > float(ema20.iloc[-3]):
        score += 10

    if len(df) >= 2 and float(today["Low"]) > float(df.iloc[-2]["Low"]):
        score += 10

    if _upper_wick(today) > 0.35: score -= 15
    if _close_ratio(today) < 0.65: score -= 15

    rsi_val = _rsi(df["Close"])
    if rsi_val > 75: score -= 10

    if len(df) >= 3:
        two_day = (float(today["Close"]) - float(df.iloc[-3]["Close"])) / float(df.iloc[-3]["Close"]) * 100
        if two_day > 18: score -= 20

    if score >= 40:
        return "HIGH CONTINUATION"
    elif score <= -10:
        return "ONE DAY SPIKE"
    elif score <= 10:
        return "POSSIBLE EXHAUSTION"
    return ""


# ---------------------------------------------------------------------------
# Main Scan Functions
# ---------------------------------------------------------------------------

def run_bpjs_scan(top_n: int = None) -> List[StockCandidate]:
    if top_n is None:
        top_n = settings.TOP_N_RESULTS

    logger.info(f"=== BPJS Scan — {market_status_msg()} ===")
    clear_cache()

    tickers = get_idx_tickers()
    data    = fetch_batch(tickers, interval="5m")

    passed     = 0
    rejected   = 0
    candidates = []

    for ticker, (df_i, df_d) in data.items():
        df = df_d if df_d is not None else df_i
        if df is None or df.empty or len(df) < 10:
            continue

        # Run full filter pipeline
        ok, reason = _run_filter_pipeline_bpjs(df)
        if not ok:
            rejected += 1
            logger.debug(f"BPJS REJECT {ticker}: {reason}")
            continue

        passed += 1

        # Score untuk ranking
        score, signals = _score_passed(df, "BPJS")

        # ARA detection
        is_ara, ara_score, ara_sigs = _detect_ara(df)
        if is_ara:
            for s in ara_sigs:
                if s not in signals:
                    signals.append(s)

        # Continuation label
        cont_label = _get_continuation_label(df)

        avg_vol  = float(df["Volume"].iloc[-21:-1].mean())
        rel_vol  = float(df["Volume"].iloc[-1]) / avg_vol if avg_vol > 0 else 1.0
        pct      = _pct_change(df)

        candidates.append(StockCandidate(
            ticker=ticker,
            score=score,
            price=float(df["Close"].iloc[-1]),
            mode="BPJS",
            signals_triggered=signals,
            rel_volume=rel_vol,
            price_change_pct=pct,
            rsi=_rsi(df["Close"]),
            traded_value_idr=float(df["Close"].iloc[-1] * df["Volume"].iloc[-1]),
            ara_potential=is_ara,
            ara_score=ara_score,
            continuation_label=cont_label,
        ))

    # Sort: ARA > HIGH CONTINUATION > score
    def sort_key(c):
        cont_p = {"HIGH CONTINUATION": 2, "": 1, "POSSIBLE EXHAUSTION": 0, "ONE DAY SPIKE": -1}
        return (c.ara_potential, cont_p.get(c.continuation_label, 0), c.score)

    candidates.sort(key=sort_key, reverse=True)
    logger.info(
        f"BPJS: {passed} lolos filter dari {passed+rejected} valid ticker | "
        f"{len(candidates)} kandidat | "
        f"{sum(1 for c in candidates if c.ara_potential)} ARA | "
        f"{sum(1 for c in candidates if c.continuation_label=='HIGH CONTINUATION')} HIGH CONT"
    )
    return candidates[:top_n]


def run_bsjp_scan(top_n: int = None) -> List[StockCandidate]:
    if top_n is None:
        top_n = settings.TOP_N_RESULTS

    logger.info(f"=== BSJP Scan — {market_status_msg()} ===")
    clear_cache()

    tickers = get_idx_tickers()
    data    = fetch_batch(tickers, interval="15m")

    passed     = 0
    rejected   = 0
    candidates = []

    for ticker, (df_i, df_d) in data.items():
        df = df_d if df_d is not None else df_i
        if df is None or df.empty or len(df) < 10:
            continue

        ok, reason = _run_filter_pipeline_bsjp(df)
        if not ok:
            rejected += 1
            logger.debug(f"BSJP REJECT {ticker}: {reason}")
            continue

        passed += 1
        score, signals = _score_passed(df, "BSJP")

        is_ara, ara_score, ara_sigs = _detect_ara(df)
        if is_ara:
            for s in ara_sigs:
                if s not in signals:
                    signals.append(s)

        cont_label = _get_continuation_label(df)

        avg_vol = float(df["Volume"].iloc[-21:-1].mean())
        rel_vol = float(df["Volume"].iloc[-1]) / avg_vol if avg_vol > 0 else 1.0
        pct     = _pct_change(df)

        candidates.append(StockCandidate(
            ticker=ticker,
            score=score,
            price=float(df["Close"].iloc[-1]),
            mode="BSJP",
            signals_triggered=signals,
            rel_volume=rel_vol,
            price_change_pct=pct,
            rsi=_rsi(df["Close"]),
            traded_value_idr=float(df["Close"].iloc[-1] * df["Volume"].iloc[-1]),
            ara_potential=is_ara,
            ara_score=ara_score,
            continuation_label=cont_label,
        ))

    def sort_key(c):
        cont_p = {"HIGH CONTINUATION": 2, "": 1, "POSSIBLE EXHAUSTION": 0, "ONE DAY SPIKE": -1}
        return (c.ara_potential, cont_p.get(c.continuation_label, 0), c.score)

    candidates.sort(key=sort_key, reverse=True)
    logger.info(
        f"BSJP: {passed} lolos filter dari {passed+rejected} valid ticker | "
        f"{len(candidates)} kandidat | "
        f"{sum(1 for c in candidates if c.ara_potential)} ARA"
    )
    return candidates[:top_n]


def run_full_scan(top_n: int = None) -> Dict[str, List[StockCandidate]]:
    return {
        "bpjs": run_bpjs_scan(top_n),
        "bsjp": run_bsjp_scan(top_n),
    }


def run_combined_top_scan(top_n: int = None):
    return run_bpjs_scan(top_n), run_bsjp_scan(top_n)

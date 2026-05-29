"""
screener/scanner.py — Filter Pipeline v4

Adjustment dari v3:
- GATE 1: Value turun 1B (dari 2B) — saham midcap tetap masuk
- GATE 2: Close ratio turun 0.50 (dari 0.60), wick naik 0.50 (dari 0.40)
- GATE 3: Volume minimum 1.2x (dari 1.5x)
- GATE 4: EMA check dilonggarkan — boleh sedikit di bawah EMA20
           EMA trend check dihapus (terlalu ketat)
           Lower low check dihapus (sudah ada di Gate 2)
- GATE 5: RSI naik 85 (dari 80), 2-day gain naik 30% (dari 25%)
- GATE 6: Persyaratan fresh setup dilonggarkan — cukup 1 dari 4 kondisi
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
# Indicators
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
# BPJS Filter Pipeline
# ---------------------------------------------------------------------------

def _filter_bpjs(df: pd.DataFrame) -> Tuple[bool, str]:
    if len(df) < 10:
        return False, "data tidak cukup"

    today     = df.iloc[-1]
    prev      = df.iloc[-2]
    avg_vol   = float(df["Volume"].iloc[-21:-1].mean())
    today_vol = float(today["Volume"])
    rel_vol   = today_vol / avg_vol if avg_vol > 0 else 1.0
    traded_val = float(today["Close"]) * today_vol
    pct        = _pct_change(df)
    rsi_val    = _rsi(df["Close"])
    ema20_val  = float(_ema(df["Close"], 20).iloc[-1])

    # GATE 1: LIQUIDITY & BASIC
    if traded_val < 1_000_000_000:
        return False, f"value {traded_val/1e9:.1f}B < 1B"
    if float(today["Close"]) < settings.MIN_PRICE_IDR:
        return False, "harga terlalu rendah"
    if pct <= 0:
        return False, f"harga turun ({pct:.1f}%)"

    # GATE 2: CANDLE STRUCTURE
    if _upper_wick(today) > 0.50:
        return False, f"upper wick ekstrem ({_upper_wick(today):.0%})"
    if _close_ratio(today) < 0.50:
        return False, f"close sangat lemah ({_close_ratio(today):.0%})"
    if _body(today) < 0.15:
        return False, "doji ekstrem"

    # GATE 3: VOLUME
    if rel_vol < 1.2:
        return False, f"volume lemah ({rel_vol:.1f}x)"
    if rel_vol > 25.0 and pct < 1.5:
        return False, f"volume spike tidak wajar"

    # GATE 4: TREND — tidak terlalu ketat
    # Boleh sedikit di bawah EMA20 (max 3%)
    if ema20_val > 0:
        dist_below = (ema20_val - float(today["Close"])) / ema20_val * 100
        if dist_below > 3.0:
            return False, f"terlalu jauh di bawah EMA20 ({dist_below:.1f}%)"

    # GATE 5: ANTI-ENDGAME
    if rsi_val > 85:
        return False, f"RSI overbought ({rsi_val:.0f})"
    if len(df) >= 3:
        two_day = (float(today["Close"]) - float(df.iloc[-3]["Close"])) / float(df.iloc[-3]["Close"]) * 100
        if two_day > 30.0:
            return False, f"naik {two_day:.0f}% dalam 2 hari"
    if ema20_val > 0:
        dist_above = (float(today["Close"]) - ema20_val) / ema20_val * 100
        if dist_above > 30.0:
            return False, f"terlalu jauh di atas EMA20 ({dist_above:.0f}%)"

    # GATE 6: FRESH SETUP — cukup 1 kondisi terpenuhi
    lookback    = min(10, len(df) - 1)
    prior       = df.iloc[-(lookback+1):-1]
    consol_high = float(prior["High"].max())
    consol_low  = float(prior["Low"].min())

    is_breakout      = float(today["Close"]) > consol_high
    is_new_momentum  = pct >= 1.0 and rel_vol >= 1.5
    is_accum         = False
    is_higher_low    = float(today["Low"]) > float(prev["Low"])

    if len(df) >= 4:
        vol_trend = sum(
            1 for i in range(1, 4)
            if float(df["Volume"].iloc[-i]) >= float(df["Volume"].iloc[-i-1])
        ) >= 2
        price_range = (consol_high - consol_low) / consol_low * 100 if consol_low > 0 else 99
        is_accum = vol_trend and price_range < 15.0

    if not any([is_breakout, is_new_momentum, is_accum, is_higher_low]):
        return False, "tidak ada fresh setup"

    return True, ""


# ---------------------------------------------------------------------------
# BSJP Filter Pipeline
# ---------------------------------------------------------------------------

def _filter_bsjp(df: pd.DataFrame) -> Tuple[bool, str]:
    if len(df) < 10:
        return False, "data tidak cukup"

    today     = df.iloc[-1]
    prev      = df.iloc[-2]
    avg_vol   = float(df["Volume"].iloc[-21:-1].mean())
    today_vol = float(today["Volume"])
    rel_vol   = today_vol / avg_vol if avg_vol > 0 else 1.0
    traded_val = float(today["Close"]) * today_vol
    pct        = _pct_change(df)
    rsi_val    = _rsi(df["Close"])
    ema20_val  = float(_ema(df["Close"], 20).iloc[-1])

    # GATE 1: LIQUIDITY
    if traded_val < 500_000_000:
        return False, f"value {traded_val/1e9:.2f}B < 0.5B"
    if float(today["Close"]) < settings.MIN_PRICE_IDR:
        return False, "harga terlalu rendah"

    # GATE 2: STRONG CLOSE
    if _close_ratio(today) < 0.75:
        return False, f"close lemah ({_close_ratio(today):.0%})"
    if _upper_wick(today) > 0.35:
        return False, f"upper wick ({_upper_wick(today):.0%})"

    # GATE 3: VOLUME
    if rel_vol < 1.2:
        return False, f"volume lemah ({rel_vol:.1f}x)"

    # GATE 4: TREND
    if ema20_val > 0:
        dist_below = (ema20_val - float(today["Close"])) / ema20_val * 100
        if dist_below > 5.0:
            return False, f"di bawah EMA20 ({dist_below:.1f}%)"

    # GATE 5: ANTI-ENDGAME
    if rsi_val > 82:
        return False, f"RSI tinggi ({rsi_val:.0f})"
    if len(df) >= 3:
        two_day = (float(today["Close"]) - float(df.iloc[-3]["Close"])) / float(df.iloc[-3]["Close"]) * 100
        if two_day > 25.0:
            return False, f"naik {two_day:.0f}% 2 hari"
    if ema20_val > 0:
        dist_above = (float(today["Close"]) - ema20_val) / ema20_val * 100
        if dist_above > 25.0:
            return False, f"terlalu jauh EMA20"

    # GATE 6: OVERNIGHT SETUP
    higher_low     = float(today["Low"]) >= float(prev["Low"])
    no_panic       = float(today["Close"]) >= float(prev["Close"])
    vol_accum      = rel_vol >= 1.5
    resist         = float(df["High"].iloc[-21:-1].max())
    break_resist   = float(today["Close"]) > resist

    if not any([higher_low, no_panic, break_resist, vol_accum]):
        return False, "tidak ada setup overnight"

    return True, ""


# ---------------------------------------------------------------------------
# Scoring & Labels
# ---------------------------------------------------------------------------

def _score(df: pd.DataFrame, mode: str) -> Tuple[int, List[str]]:
    score  = 50
    signals = []
    today  = df.iloc[-1]
    avg_vol = float(df["Volume"].iloc[-21:-1].mean())
    rel_vol = float(today["Volume"]) / avg_vol if avg_vol > 0 else 1.0
    pct     = _pct_change(df)
    rsi_val = _rsi(df["Close"])
    ema20   = _ema(df["Close"], 20)
    cr      = _close_ratio(today)
    uw      = _upper_wick(today)

    # Volume
    if rel_vol >= 5.0:   score += 15; signals.append(f"Volume {rel_vol:.1f}x")
    elif rel_vol >= 3.0: score += 10; signals.append(f"Volume {rel_vol:.1f}x")
    elif rel_vol >= 2.0: score += 5;  signals.append(f"Volume {rel_vol:.1f}x")

    # Move
    if mode == "BPJS":
        if 3.0 <= pct <= 8.0:   score += 10; signals.append(f"Move {pct:.1f}%")
        elif 1.0 <= pct < 3.0:  score += 5;  signals.append(f"Move {pct:.1f}%")

    # Close quality
    if cr >= 0.90:   score += 10; signals.append("Close Near High")
    elif cr >= 0.75: score += 5

    # Clean candle
    if uw < 0.15:   score += 10; signals.append("Clean Candle")
    elif uw < 0.25: score += 5

    # EMA trending up
    if len(ema20) >= 5:
        slope = (float(ema20.iloc[-1]) - float(ema20.iloc[-5])) / float(ema20.iloc[-5]) * 100
        if slope > 0.5: score += 5; signals.append("EMA Trending Up")

    # Fresh breakout
    lookback    = min(10, len(df) - 1)
    prior       = df.iloc[-(lookback+1):-1]
    consol_high = float(prior["High"].max())
    if float(today["Close"]) > consol_high:
        score += 10; signals.append("Fresh Breakout")

    # RSI sweet spot
    if 45 <= rsi_val <= 65:   score += 5; signals.append("RSI Ideal")
    elif 65 < rsi_val <= 75:  score += 2

    # Higher low
    if len(df) >= 2 and float(today["Low"]) > float(df.iloc[-2]["Low"]):
        score += 5; signals.append("Higher Low")

    # BSJP: resistance breakout
    if mode == "BSJP":
        resist = float(df["High"].iloc[-21:-1].max())
        if float(today["Close"]) > resist:
            score += 10; signals.append("Resistance Breakout")

    # Accumulation
    if len(df) >= 4:
        vol_trend = sum(
            1 for i in range(1, 4)
            if float(df["Volume"].iloc[-i]) >= float(df["Volume"].iloc[-i-1])
        ) >= 2
        price_range = (consol_high - float(prior["Low"].min())) / float(prior["Low"].min()) * 100 \
            if float(prior["Low"].min()) > 0 else 99
        if vol_trend and price_range < 15.0:
            score += 8; signals.append("Akumulasi")

    return min(score, 100), signals


def _ara_detect(df: pd.DataFrame) -> Tuple[bool, int, List[str]]:
    if len(df) < 5: return False, 0, []
    today    = df.iloc[-1]
    avg_vol  = float(df["Volume"].iloc[-21:-1].mean())
    rel_vol  = float(today["Volume"]) / avg_vol if avg_vol > 0 else 1.0
    s, sigs  = 0, []

    if rel_vol >= 5.0:   s += 30; sigs.append(f"Vol {rel_vol:.1f}x")
    elif rel_vol >= 3.0: s += 15

    cr = _close_ratio(today)
    if cr >= 0.97: s += 25; sigs.append("Close = High")
    elif cr >= 0.92: s += 12

    if _body(today) >= 0.80: s += 15; sigs.append("Candle Kuat")
    elif _body(today) >= 0.65: s += 8

    lookback = min(10, len(df)-1)
    prior    = df.iloc[-(lookback+1):-1]
    ch       = float(prior["High"].max())
    cl       = float(prior["Low"].min())
    if cl > 0:
        cr_pct = (ch - cl) / cl * 100
        pct    = _pct_change(df)
        if cr_pct < 5.0 and pct >= 5.0:   s += 20; sigs.append("Breakout Konsolidasi Ketat")
        elif cr_pct < 8.0 and pct >= 3.0: s += 10

    if len(df) >= 4:
        vt = all(float(df["Volume"].iloc[-i]) >= float(df["Volume"].iloc[-i-1]) for i in range(1, 4))
        if vt and abs(_pct_change(df)) < 3.0: s += 10; sigs.append("Akumulasi Tersembunyi")

    return s >= 45, min(s, 100), sigs


def _continuation_label(df: pd.DataFrame) -> str:
    if len(df) < 3: return ""
    today = df.iloc[-1]
    s = 0
    if _close_ratio(today) >= 0.88: s += 20
    if _upper_wick(today) < 0.15:   s += 15
    if _body(today) > 0.70:         s += 10

    avg_vol = float(df["Volume"].iloc[-21:-1].mean())
    if avg_vol > 0 and float(today["Volume"]) >= avg_vol * 1.5: s += 10

    ema20 = _ema(df["Close"], 20)
    if len(ema20) >= 3 and float(ema20.iloc[-1]) > float(ema20.iloc[-3]): s += 10
    if len(df) >= 2 and float(today["Low"]) > float(df.iloc[-2]["Low"]): s += 10

    if _upper_wick(today) > 0.35:   s -= 15
    if _close_ratio(today) < 0.65:  s -= 15
    if _rsi(df["Close"]) > 75:      s -= 10
    if len(df) >= 3:
        two_day = (float(today["Close"]) - float(df.iloc[-3]["Close"])) / float(df.iloc[-3]["Close"]) * 100
        if two_day > 18: s -= 20

    if s >= 40:   return "HIGH CONTINUATION"
    if s <= -10:  return "ONE DAY SPIKE"
    if s <= 10:   return "POSSIBLE EXHAUSTION"
    return ""


# ---------------------------------------------------------------------------
# Scan functions
# ---------------------------------------------------------------------------

def _build(ticker, df, mode) -> StockCandidate:
    score, sigs = _score(df, mode)
    is_ara, ara_s, ara_sigs = _ara_detect(df)
    for s in ara_sigs:
        if s not in sigs: sigs.append(s)
    cont = _continuation_label(df)
    avg_vol = float(df["Volume"].iloc[-21:-1].mean())
    return StockCandidate(
        ticker=ticker, score=score, price=float(df["Close"].iloc[-1]),
        mode=mode, signals_triggered=sigs,
        rel_volume=float(df["Volume"].iloc[-1]) / avg_vol if avg_vol > 0 else 1.0,
        price_change_pct=_pct_change(df),
        rsi=_rsi(df["Close"]),
        traded_value_idr=float(df["Close"].iloc[-1] * df["Volume"].iloc[-1]),
        ara_potential=is_ara, ara_score=ara_s, continuation_label=cont,
    )


def _sort_key(c):
    p = {"HIGH CONTINUATION": 2, "": 1, "POSSIBLE EXHAUSTION": 0, "ONE DAY SPIKE": -1}
    return (c.ara_potential, p.get(c.continuation_label, 0), c.score)


def run_bpjs_scan(top_n: int = None) -> List[StockCandidate]:
    if top_n is None: top_n = settings.TOP_N_RESULTS
    logger.info(f"=== BPJS Scan — {market_status_msg()} ===")
    clear_cache()
    data = fetch_batch(get_idx_tickers(), interval="5m")
    candidates, passed, rejected = [], 0, 0
    for ticker, (df_i, df_d) in data.items():
        df = df_d if df_d is not None else df_i
        if df is None or df.empty or len(df) < 10: continue
        ok, reason = _filter_bpjs(df)
        if not ok:
            rejected += 1
            logger.debug(f"BPJS REJECT {ticker}: {reason}")
            continue
        passed += 1
        candidates.append(_build(ticker, df, "BPJS"))
    candidates.sort(key=_sort_key, reverse=True)
    logger.info(f"BPJS: {passed} lolos / {passed+rejected} valid | {len(candidates)} kandidat")
    return candidates[:top_n]


def run_bsjp_scan(top_n: int = None) -> List[StockCandidate]:
    if top_n is None: top_n = settings.TOP_N_RESULTS
    logger.info(f"=== BSJP Scan — {market_status_msg()} ===")
    clear_cache()
    data = fetch_batch(get_idx_tickers(), interval="15m")
    candidates, passed, rejected = [], 0, 0
    for ticker, (df_i, df_d) in data.items():
        df = df_d if df_d is not None else df_i
        if df is None or df.empty or len(df) < 10: continue
        ok, reason = _filter_bsjp(df)
        if not ok:
            rejected += 1
            logger.debug(f"BSJP REJECT {ticker}: {reason}")
            continue
        passed += 1
        candidates.append(_build(ticker, df, "BSJP"))
    candidates.sort(key=_sort_key, reverse=True)
    logger.info(f"BSJP: {passed} lolos / {passed+rejected} valid | {len(candidates)} kandidat")
    return candidates[:top_n]


def run_full_scan(top_n: int = None) -> Dict[str, List[StockCandidate]]:
    return {"bpjs": run_bpjs_scan(top_n), "bsjp": run_bsjp_scan(top_n)}


def run_combined_top_scan(top_n: int = None):
    return run_bpjs_scan(top_n), run_bsjp_scan(top_n)

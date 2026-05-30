"""
screener/scanner.py — Intraday Mode v5

Sekarang pakai data intraday (5m/15m) yang sesungguhnya.

BPJS: pakai 5m intraday → nangkep early move dari awal session
BSJP: pakai 15m intraday → cek kondisi sore hari

Untuk indicator baseline (EMA, RSI, resistance):
→ pakai daily data supaya konteks lebih akurat

Logic:
- Relative volume = volume intraday vs rata-rata daily volume
- Price move = % dari open HARI INI (bukan close kemarin)
- VWAP = calculated dari intraday bars
- EMA20 = dari daily data (lebih stabil)
- Higher low = dari intraday bars
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
from services.market_data import fetch_batch, clear_cache

logger = logging.getLogger(__name__)
WIB = pytz.timezone("Asia/Jakarta")


def market_status_msg() -> str:
    now   = datetime.now(WIB)
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


def _vwap(df: pd.DataFrame) -> float:
    """VWAP dari intraday bars."""
    try:
        tp     = (df["High"] + df["Low"] + df["Close"]) / 3
        cum_tv = (tp * df["Volume"]).cumsum()
        cum_v  = df["Volume"].cumsum()
        vwap_s = cum_tv / cum_v.replace(0, float("nan"))
        return float(vwap_s.iloc[-1])
    except Exception:
        return 0.0


def _pct_from_open(df_intraday: pd.DataFrame) -> float:
    """% dari open hari ini — true intraday move."""
    if df_intraday.empty:
        return 0.0
    open_p  = float(df_intraday["Open"].iloc[0])
    close_p = float(df_intraday["Close"].iloc[-1])
    return (close_p - open_p) / open_p * 100 if open_p > 0 else 0.0


def _rel_volume(df_intraday: pd.DataFrame, df_daily: pd.DataFrame) -> float:
    """
    Volume hari ini (projected full day) vs rata-rata daily volume.
    Project dengan asumsi sesi IDX = 390 menit, 5m = 78 bars.
    """
    try:
        today_vol = float(df_intraday["Volume"].sum())
        bars_so_far = len(df_intraday)
        full_bars   = 78  # full session 5m
        projected   = today_vol * (full_bars / max(bars_so_far, 1))

        avg_daily = float(df_daily["Volume"].tail(20).mean())
        if avg_daily <= 0:
            return 1.0
        return projected / avg_daily
    except Exception:
        return 1.0


def _upper_wick(row: pd.Series) -> float:
    rng = float(row["High"]) - float(row["Low"])
    if rng <= 0: return 0.0
    wick = float(row["High"]) - max(float(row["Open"]), float(row["Close"]))
    return max(0.0, wick / rng)


def _body(row: pd.Series) -> float:
    rng = float(row["High"]) - float(row["Low"])
    if rng <= 0: return 0.0
    return abs(float(row["Close"]) - float(row["Open"])) / rng


def _close_ratio_intraday(df: pd.DataFrame) -> float:
    """Close dalam range high-low HARI INI."""
    day_high = float(df["High"].max())
    day_low  = float(df["Low"].min())
    close    = float(df["Close"].iloc[-1])
    rng      = day_high - day_low
    return (close - day_low) / rng if rng > 0 else 1.0


def _traded_value(df_intraday: pd.DataFrame) -> float:
    return float((df_intraday["Close"] * df_intraday["Volume"]).sum())


# ---------------------------------------------------------------------------
# Filter Pipeline — BPJS (Intraday 5m)
# ---------------------------------------------------------------------------

def _filter_bpjs(df_i: pd.DataFrame, df_d: pd.DataFrame) -> Tuple[bool, str]:
    """
    Filter BPJS menggunakan intraday data sesungguhnya.
    df_i = 5m intraday bars hari ini
    df_d = daily bars untuk baseline
    """
    if df_i is None or df_i.empty or len(df_i) < 3:
        return False, "intraday data kosong"
    if df_d is None or df_d.empty or len(df_d) < 10:
        return False, "daily data kosong"

    price      = float(df_i["Close"].iloc[-1])
    pct        = _pct_from_open(df_i)
    rel_vol    = _rel_volume(df_i, df_d)
    traded_val = _traded_value(df_i)
    last_bar   = df_i.iloc[-1]
    vwap_val   = _vwap(df_i)

    # EMA20 dari daily
    ema20_daily = float(_ema(df_d["Close"], 20).iloc[-1])

    # RSI dari daily
    rsi_val = _rsi(df_d["Close"])

    # GATE 1: LIQUIDITY
    if traded_val < 500_000_000:
        return False, f"value {traded_val/1e9:.2f}B < 0.5B"
    if price < settings.MIN_PRICE_IDR:
        return False, "harga terlalu rendah"

    # GATE 2: PRICE MOVING UP
    # Minimal sudah naik 0.5% dari open
    if pct < 0.5:
        return False, f"belum bergerak ({pct:.1f}% dari open)"

    # GATE 3: VOLUME
    if rel_vol < 1.0:
        return False, f"volume lemah ({rel_vol:.1f}x projected)"

    # GATE 4: CANDLE QUALITY
    if _upper_wick(last_bar) > 0.55:
        return False, f"upper wick terlalu panjang"
    if _body(last_bar) < 0.10:
        return False, "doji"

    # GATE 5: ABOVE VWAP (sinyal bullish intraday paling kuat)
    if vwap_val > 0 and price < vwap_val * 0.98:
        return False, f"di bawah VWAP ({price:.0f} < {vwap_val:.0f})"

    # GATE 6: NOT ENDGAME
    if rsi_val > 85:
        return False, f"RSI overbought ({rsi_val:.0f})"

    # Kalau sudah naik >15% dari open dalam satu hari = terlalu extended
    if pct > 15.0:
        return False, f"sudah naik {pct:.0f}% dari open hari ini"

    # GATE 7: TREND CONTEXT (dari daily)
    # Tidak wajib di atas EMA20, tapi tidak boleh terlalu jauh di bawah
    if ema20_daily > 0:
        dist_below = (ema20_daily - price) / ema20_daily * 100
        if dist_below > 5.0:
            return False, f"terlalu jauh di bawah EMA20 daily"

    return True, ""


# ---------------------------------------------------------------------------
# Filter Pipeline — BSJP (Intraday 15m)
# ---------------------------------------------------------------------------

def _filter_bsjp(df_i: pd.DataFrame, df_d: pd.DataFrame) -> Tuple[bool, str]:
    """
    Filter BSJP menggunakan intraday 15m data.
    Fokus: strong close, accumulation sore.
    """
    if df_i is None or df_i.empty or len(df_i) < 3:
        return False, "intraday data kosong"
    if df_d is None or df_d.empty or len(df_d) < 10:
        return False, "daily data kosong"

    price      = float(df_i["Close"].iloc[-1])
    pct        = _pct_from_open(df_i)
    rel_vol    = _rel_volume(df_i, df_d)
    traded_val = _traded_value(df_i)
    last_bar   = df_i.iloc[-1]
    cr         = _close_ratio_intraday(df_i)

    ema20_daily = float(_ema(df_d["Close"], 20).iloc[-1])
    rsi_val     = _rsi(df_d["Close"])

    # GATE 1: LIQUIDITY
    if traded_val < 300_000_000:
        return False, f"value {traded_val/1e9:.2f}B < 0.3B"
    if price < settings.MIN_PRICE_IDR:
        return False, "harga terlalu rendah"

    # GATE 2: STRONG CLOSE — close harus dekat high hari ini
    if cr < 0.75:
        return False, f"close lemah ({cr:.0%} dari range)"

    # GATE 3: UPPER WICK — tidak boleh ada rejection kuat
    if _upper_wick(last_bar) > 0.35:
        return False, f"upper wick ({_upper_wick(last_bar):.0%})"

    # GATE 4: VOLUME
    if rel_vol < 1.0:
        return False, f"volume lemah ({rel_vol:.1f}x)"

    # GATE 5: NOT ENDGAME
    if rsi_val > 82:
        return False, f"RSI tinggi ({rsi_val:.0f})"
    if pct > 20.0:
        return False, f"sudah naik {pct:.0f}% hari ini"

    # GATE 6: TREND CONTEXT
    if ema20_daily > 0:
        dist_below = (ema20_daily - price) / ema20_daily * 100
        if dist_below > 8.0:
            return False, f"terlalu jauh di bawah EMA20"

    return True, ""


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def _score(df_i: pd.DataFrame, df_d: pd.DataFrame, mode: str) -> Tuple[int, List[str]]:
    score  = 50
    signals = []

    price      = float(df_i["Close"].iloc[-1])
    pct        = _pct_from_open(df_i)
    rel_vol    = _rel_volume(df_i, df_d)
    last_bar   = df_i.iloc[-1]
    vwap_val   = _vwap(df_i)
    cr         = _close_ratio_intraday(df_i)
    uw         = _upper_wick(last_bar)
    rsi_val    = _rsi(df_d["Close"])
    ema20_d    = _ema(df_d["Close"], 20)
    ema20_val  = float(ema20_d.iloc[-1])

    # Volume
    if rel_vol >= 5.0:   score += 15; signals.append(f"Volume {rel_vol:.1f}x")
    elif rel_vol >= 3.0: score += 10; signals.append(f"Volume {rel_vol:.1f}x")
    elif rel_vol >= 2.0: score += 5;  signals.append(f"Volume {rel_vol:.1f}x")

    # Move dari open
    if mode == "BPJS":
        if 3.0 <= pct <= 8.0:  score += 10; signals.append(f"Move +{pct:.1f}%")
        elif 1.0 <= pct < 3.0: score += 5;  signals.append(f"Move +{pct:.1f}%")

    # Above VWAP
    if vwap_val > 0 and price > vwap_val:
        score += 10; signals.append("Above VWAP")

    # Close quality
    if cr >= 0.90:   score += 10; signals.append("Close Near High")
    elif cr >= 0.75: score += 5

    # Clean candle
    if uw < 0.15:   score += 8; signals.append("Clean Candle")
    elif uw < 0.25: score += 4

    # RSI sweet spot
    if 40 <= rsi_val <= 65:  score += 5; signals.append("RSI Ideal")
    elif 65 < rsi_val <= 75: score += 2

    # EMA20 daily alignment
    if ema20_val > 0 and price > ema20_val:
        score += 5; signals.append("Above EMA20")
        # EMA trending up
        if len(ema20_d) >= 5:
            slope = (float(ema20_d.iloc[-1]) - float(ema20_d.iloc[-5])) / float(ema20_d.iloc[-5]) * 100
            if slope > 0.3: score += 3; signals.append("EMA Trending Up")

    # Higher low intraday
    if len(df_i) >= 3:
        recent_lows = df_i["Low"].tail(4).values
        if all(recent_lows[i] >= recent_lows[i-1] for i in range(1, len(recent_lows))):
            score += 5; signals.append("Higher Low")

    # Resistance breakout (dari daily)
    if len(df_d) >= 5:
        resist = float(df_d["High"].iloc[-21:-1].max())
        if price > resist:
            score += 8; signals.append("Resistance Breakout")

    # BSJP specific
    if mode == "BSJP":
        # Last hour accumulation: volume candle terakhir > rata-rata
        avg_bar_vol = float(df_i["Volume"].mean())
        last_vol    = float(df_i["Volume"].tail(3).mean())
        if avg_bar_vol > 0 and last_vol > avg_bar_vol * 1.3:
            score += 8; signals.append("Last Hour Accumulation")

    return min(score, 100), signals


# ---------------------------------------------------------------------------
# ARA & Labels
# ---------------------------------------------------------------------------

def _ara_detect(df_i: pd.DataFrame, df_d: pd.DataFrame) -> Tuple[bool, int, List[str]]:
    s, sigs = 0, []
    if df_i is None or df_i.empty: return False, 0, []

    rel_vol = _rel_volume(df_i, df_d)
    pct     = _pct_from_open(df_i)
    cr      = _close_ratio_intraday(df_i)
    last    = df_i.iloc[-1]

    if rel_vol >= 5.0:  s += 30; sigs.append(f"Vol {rel_vol:.1f}x")
    elif rel_vol >= 3.0: s += 15

    if cr >= 0.97: s += 25; sigs.append("Close = High")
    elif cr >= 0.92: s += 12

    if _body(last) >= 0.80: s += 15; sigs.append("Candle Kuat")
    elif _body(last) >= 0.65: s += 8

    # Breakout dari konsolidasi daily
    if df_d is not None and len(df_d) >= 5:
        prior = df_d.iloc[-11:-1]
        ch    = float(prior["High"].max())
        cl    = float(prior["Low"].min())
        if cl > 0:
            rng = (ch - cl) / cl * 100
            if rng < 5.0 and pct >= 5.0:   s += 20; sigs.append("Breakout Konsolidasi Ketat")
            elif rng < 8.0 and pct >= 3.0: s += 10

    return s >= 45, min(s, 100), sigs


def _cont_label(df_i: pd.DataFrame, df_d: pd.DataFrame) -> str:
    if df_i is None or df_i.empty: return ""
    s  = 0
    cr = _close_ratio_intraday(df_i)
    uw = _upper_wick(df_i.iloc[-1])

    if cr >= 0.88:  s += 20
    if uw < 0.15:   s += 15
    if _body(df_i.iloc[-1]) > 0.70: s += 10

    rel_vol = _rel_volume(df_i, df_d)
    if rel_vol >= 1.5: s += 10

    if len(df_i) >= 3:
        lows = df_i["Low"].tail(3).values
        if all(lows[i] >= lows[i-1] for i in range(1, len(lows))): s += 10

    if uw > 0.35:  s -= 15
    if cr < 0.65:  s -= 15
    if _rsi(df_d["Close"]) > 75: s -= 10

    if s >= 40:  return "HIGH CONTINUATION"
    if s <= -10: return "ONE DAY SPIKE"
    if s <= 10:  return "POSSIBLE EXHAUSTION"
    return ""


# ---------------------------------------------------------------------------
# Scan functions
# ---------------------------------------------------------------------------

def _build(ticker, df_i, df_d, mode) -> StockCandidate:
    score, sigs    = _score(df_i, df_d, mode)
    is_ara, ara_s, ara_sigs = _ara_detect(df_i, df_d)
    for s in ara_sigs:
        if s not in sigs: sigs.append(s)
    cont   = _cont_label(df_i, df_d)
    rel_vol = _rel_volume(df_i, df_d)

    return StockCandidate(
        ticker=ticker, score=score,
        price=float(df_i["Close"].iloc[-1]),
        mode=mode, signals_triggered=sigs,
        rel_volume=rel_vol,
        price_change_pct=_pct_from_open(df_i),
        rsi=_rsi(df_d["Close"]),
        traded_value_idr=_traded_value(df_i),
        ara_potential=is_ara, ara_score=ara_s,
        continuation_label=cont,
    )


def _sort_key(c):
    p = {"HIGH CONTINUATION": 2, "": 1, "POSSIBLE EXHAUSTION": 0, "ONE DAY SPIKE": -1}
    return (c.ara_potential, p.get(c.continuation_label, 0), c.score)


def run_bpjs_scan(top_n: int = None) -> List[StockCandidate]:
    if top_n is None: top_n = settings.TOP_N_RESULTS
    logger.info(f"=== BPJS Scan (5m intraday) — {market_status_msg()} ===")
    clear_cache()
    data = fetch_batch(get_idx_tickers(), interval="5m")
    candidates, passed, rejected = [], 0, 0

    for ticker, (df_i, df_d) in data.items():
        if df_i is None or df_d is None: continue
        ok, reason = _filter_bpjs(df_i, df_d)
        if not ok:
            rejected += 1
            logger.debug(f"BPJS REJECT {ticker}: {reason}")
            continue
        passed += 1
        candidates.append(_build(ticker, df_i, df_d, "BPJS"))

    candidates.sort(key=_sort_key, reverse=True)
    logger.info(f"BPJS: {passed} lolos / {passed+rejected} valid | {len(candidates)} kandidat")
    return candidates[:top_n]


def run_bsjp_scan(top_n: int = None) -> List[StockCandidate]:
    if top_n is None: top_n = settings.TOP_N_RESULTS
    logger.info(f"=== BSJP Scan (15m intraday) — {market_status_msg()} ===")
    clear_cache()
    data = fetch_batch(get_idx_tickers(), interval="15m")
    candidates, passed, rejected = [], 0, 0

    for ticker, (df_i, df_d) in data.items():
        if df_i is None or df_d is None: continue
        ok, reason = _filter_bsjp(df_i, df_d)
        if not ok:
            rejected += 1
            logger.debug(f"BSJP REJECT {ticker}: {reason}")
            continue
        passed += 1
        candidates.append(_build(ticker, df_i, df_d, "BSJP"))

    candidates.sort(key=_sort_key, reverse=True)
    logger.info(f"BSJP: {passed} lolos / {passed+rejected} valid | {len(candidates)} kandidat")
    return candidates[:top_n]


def run_full_scan(top_n: int = None) -> Dict[str, List[StockCandidate]]:
    return {"bpjs": run_bpjs_scan(top_n), "bsjp": run_bsjp_scan(top_n)}


def run_combined_top_scan(top_n: int = None):
    return run_bpjs_scan(top_n), run_bsjp_scan(top_n)

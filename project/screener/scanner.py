"""
screener/scanner.py — v7 dengan reject reason counter
Temporary: log summary reject reasons untuk diagnosa
"""

import logging
from collections import Counter
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
    try:
        tp     = (df["High"] + df["Low"] + df["Close"]) / 3
        cum_tv = (tp * df["Volume"]).cumsum()
        cum_v  = df["Volume"].cumsum()
        return float((cum_tv / cum_v.replace(0, float("nan"))).iloc[-1])
    except Exception:
        return 0.0


def _pct_from_open(df: pd.DataFrame) -> float:
    if df.empty: return 0.0
    o = float(df["Open"].iloc[0])
    c = float(df["Close"].iloc[-1])
    return (c - o) / o * 100 if o > 0 else 0.0


def _rel_volume(df_i: pd.DataFrame, df_d: pd.DataFrame) -> float:
    try:
        today_vol   = float(df_i["Volume"].sum())
        bars_so_far = len(df_i)
        full_bars   = 78
        multiplier  = min(full_bars / max(bars_so_far, 1), 6.0)
        projected   = today_vol * multiplier
        avg_daily   = float(df_d["Volume"].tail(20).mean())
        return projected / avg_daily if avg_daily > 0 else 1.0
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


def _close_ratio(df: pd.DataFrame) -> float:
    high  = float(df["High"].max())
    low   = float(df["Low"].min())
    close = float(df["Close"].iloc[-1])
    rng   = high - low
    return (close - low) / rng if rng > 0 else 1.0


def _traded_value(df: pd.DataFrame) -> float:
    return float((df["Close"] * df["Volume"]).sum())


# ---------------------------------------------------------------------------
# BPJS Filter — dengan reject reason yang detail
# ---------------------------------------------------------------------------

def _filter_bpjs(df_i: pd.DataFrame, df_d: pd.DataFrame) -> Tuple[bool, str]:
    if df_i is None or df_i.empty or len(df_i) < 3:
        return False, "intraday kosong"
    if df_d is None or df_d.empty or len(df_d) < 10:
        return False, "daily kosong"

    price      = float(df_i["Close"].iloc[-1])
    pct        = _pct_from_open(df_i)
    rel_vol    = _rel_volume(df_i, df_d)
    traded_val = _traded_value(df_i)
    last       = df_i.iloc[-1]
    vwap_val   = _vwap(df_i)
    ema20      = float(_ema(df_d["Close"], 20).iloc[-1]) if len(df_d) >= 20 else 0.0
    rsi_val    = _rsi(df_d["Close"])

    if traded_val < 500_000_000:
        return False, f"G1:value_kecil({traded_val/1e9:.2f}B)"
    if price < settings.MIN_PRICE_IDR:
        return False, "G1:harga_rendah"
    if pct < -1.0:
        return False, f"G2:turun({pct:.1f}%)"
    if rel_vol < 1.0:
        return False, f"G3:vol_lemah({rel_vol:.1f}x)"
    if _upper_wick(last) > 0.55:
        return False, f"G4:wick({_upper_wick(last):.0%})"
    if _body(last) < 0.10:
        return False, "G4:doji"
    if len(df_i) >= 12 and vwap_val > 0 and price < vwap_val * 0.97:
        return False, f"G5:bawah_vwap({price:.0f}<{vwap_val:.0f})"
    if rsi_val > 85:
        return False, f"G6:rsi({rsi_val:.0f})"
    if pct > 15.0:
        return False, f"G6:sudah_naik({pct:.0f}%)"
    if ema20 > 0:
        dist_below = (ema20 - price) / ema20 * 100
        if dist_below > 5.0:
            return False, f"G7:bawah_ema20({dist_below:.1f}%)"

    has_volume = rel_vol >= 1.5
    has_move   = pct >= 0.5
    has_accum  = False
    if len(df_i) >= 4:
        vol_trend = sum(
            1 for i in range(1, 4)
            if float(df_i["Volume"].iloc[-i]) >= float(df_i["Volume"].iloc[-i-1])
        ) >= 2
        has_accum = vol_trend and _close_ratio(df_i) >= 0.6

    if not any([has_volume, has_move, has_accum]):
        return False, "G8:tidak_aktif"

    return True, ""


# ---------------------------------------------------------------------------
# BSJP Filter
# ---------------------------------------------------------------------------

def _filter_bsjp(df_i: pd.DataFrame, df_d: pd.DataFrame) -> Tuple[bool, str]:
    if df_i is None or df_i.empty or len(df_i) < 3:
        return False, "intraday kosong"
    if df_d is None or df_d.empty or len(df_d) < 10:
        return False, "daily kosong"

    price      = float(df_i["Close"].iloc[-1])
    pct        = _pct_from_open(df_i)
    rel_vol    = _rel_volume(df_i, df_d)
    traded_val = _traded_value(df_i)
    last       = df_i.iloc[-1]
    cr         = _close_ratio(df_i)
    ema20      = float(_ema(df_d["Close"], 20).iloc[-1]) if len(df_d) >= 20 else 0.0
    rsi_val    = _rsi(df_d["Close"])

    if traded_val < 300_000_000:
        return False, f"G1:value({traded_val/1e9:.2f}B)"
    if price < settings.MIN_PRICE_IDR:
        return False, "G1:harga_rendah"
    if cr < 0.75:
        return False, f"G2:close_lemah({cr:.0%})"
    if _upper_wick(last) > 0.35:
        return False, f"G3:wick({_upper_wick(last):.0%})"
    if rel_vol < 1.0:
        return False, f"G4:vol({rel_vol:.1f}x)"
    if rsi_val > 82:
        return False, f"G5:rsi({rsi_val:.0f})"
    if pct > 20.0:
        return False, f"G5:naik({pct:.0f}%)"
    if ema20 > 0:
        dist_below = (ema20 - price) / ema20 * 100
        if dist_below > 8.0:
            return False, f"G6:ema20({dist_below:.1f}%)"

    return True, ""


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def _score(df_i: pd.DataFrame, df_d: pd.DataFrame, mode: str) -> Tuple[int, List[str]]:
    score   = 30
    signals = []

    price     = float(df_i["Close"].iloc[-1])
    pct       = _pct_from_open(df_i)
    rel_vol   = _rel_volume(df_i, df_d)
    last      = df_i.iloc[-1]
    vwap_val  = _vwap(df_i)
    cr        = _close_ratio(df_i)
    uw        = _upper_wick(last)
    rsi_val   = _rsi(df_d["Close"])
    ema20_s   = _ema(df_d["Close"], 20)
    ema20_val = float(ema20_s.iloc[-1]) if len(ema20_s) > 0 else 0.0

    if rel_vol >= 8.0:   score += 20; signals.append(f"Volume {rel_vol:.1f}x")
    elif rel_vol >= 5.0: score += 15; signals.append(f"Volume {rel_vol:.1f}x")
    elif rel_vol >= 3.0: score += 10; signals.append(f"Volume {rel_vol:.1f}x")
    elif rel_vol >= 1.5: score += 5;  signals.append(f"Volume {rel_vol:.1f}x")

    if mode == "BPJS":
        if 5.0 <= pct <= 10.0: score += 15; signals.append(f"Move +{pct:.1f}%")
        elif 2.0 <= pct < 5.0: score += 10; signals.append(f"Move +{pct:.1f}%")
        elif 0.5 <= pct < 2.0: score += 5;  signals.append(f"Move +{pct:.1f}%")

    if vwap_val > 0 and price > vwap_val:
        score += 10; signals.append("Above VWAP")

    if cr >= 0.92:   score += 10; signals.append("Close Near High")
    elif cr >= 0.80: score += 6
    elif cr >= 0.65: score += 3

    if uw < 0.10:   score += 8; signals.append("Clean Candle")
    elif uw < 0.20: score += 4

    if 40 <= rsi_val <= 62:  score += 5; signals.append("RSI Ideal")
    elif 62 < rsi_val <= 72: score += 2

    if ema20_val > 0 and price > ema20_val:
        score += 5; signals.append("Above EMA20")
        if len(ema20_s) >= 5:
            slope = (float(ema20_s.iloc[-1]) - float(ema20_s.iloc[-5])) / float(ema20_s.iloc[-5]) * 100
            if slope > 0.3: score += 3; signals.append("EMA Trending Up")

    if len(df_i) >= 4:
        lows = df_i["Low"].tail(4).values
        if all(lows[i] >= lows[i-1] * 0.999 for i in range(1, len(lows))):
            score += 5; signals.append("Higher Low")

    if len(df_d) >= 5:
        resist = float(df_d["High"].iloc[-21:-1].max())
        if price > resist:
            score += 8; signals.append("Resistance Breakout")

    if mode == "BSJP":
        avg_bar = float(df_i["Volume"].mean())
        last_3  = float(df_i["Volume"].tail(3).mean())
        if avg_bar > 0 and last_3 > avg_bar * 1.3:
            score += 8; signals.append("Last Hour Accumulation")

    if len(df_i) >= 4:
        vol_trend = sum(
            1 for i in range(1, 4)
            if float(df_i["Volume"].iloc[-i]) >= float(df_i["Volume"].iloc[-i-1])
        ) >= 2
        if vol_trend: score += 6; signals.append("Akumulasi")

    return min(score, 100), signals


def _ara_detect(df_i, df_d):
    s, sigs = 0, []
    if df_i is None or df_i.empty: return False, 0, []
    rel_vol = _rel_volume(df_i, df_d)
    pct     = _pct_from_open(df_i)
    cr      = _close_ratio(df_i)
    last    = df_i.iloc[-1]

    if rel_vol >= 8.0:   s += 30; sigs.append(f"Vol {rel_vol:.1f}x")
    elif rel_vol >= 5.0: s += 20; sigs.append(f"Vol {rel_vol:.1f}x")
    elif rel_vol >= 3.0: s += 10

    if cr >= 0.97: s += 25; sigs.append("Close = High")
    elif cr >= 0.92: s += 12

    if _body(last) >= 0.80: s += 15; sigs.append("Candle Kuat")
    elif _body(last) >= 0.65: s += 8

    if df_d is not None and len(df_d) >= 5:
        prior = df_d.iloc[-11:-1]
        ch = float(prior["High"].max())
        cl = float(prior["Low"].min())
        if cl > 0:
            rng = (ch - cl) / cl * 100
            if rng < 5.0 and pct >= 5.0:   s += 20; sigs.append("Breakout Konsolidasi Ketat")
            elif rng < 8.0 and pct >= 3.0: s += 10

    return s >= 50, min(s, 100), sigs


def _cont_label(df_i, df_d):
    if df_i is None or df_i.empty: return ""
    s  = 0
    cr = _close_ratio(df_i)
    uw = _upper_wick(df_i.iloc[-1])

    if cr >= 0.88:  s += 20
    if uw < 0.15:   s += 15
    if _body(df_i.iloc[-1]) > 0.70: s += 10
    if _rel_volume(df_i, df_d) >= 2.0: s += 10
    if len(df_i) >= 3:
        lows = df_i["Low"].tail(3).values
        if all(lows[i] >= lows[i-1] for i in range(1, len(lows))): s += 10
    if uw > 0.35:  s -= 15
    if cr < 0.65:  s -= 15
    if _rsi(df_d["Close"]) > 75: s -= 10
    if len(df_d) >= 3:
        two_day = (float(df_d["Close"].iloc[-1]) - float(df_d["Close"].iloc[-3])) / float(df_d["Close"].iloc[-3]) * 100
        if two_day > 18: s -= 15

    if s >= 40:  return "HIGH CONTINUATION"
    if s <= -10: return "ONE DAY SPIKE"
    if s <= 10:  return "POSSIBLE EXHAUSTION"
    return ""


def _build(ticker, df_i, df_d, mode):
    score, sigs = _score(df_i, df_d, mode)
    is_ara, ara_s, ara_sigs = _ara_detect(df_i, df_d)
    for s in ara_sigs:
        if s not in sigs: sigs.append(s)
    cont    = _cont_label(df_i, df_d)
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
    logger.info(f"=== BPJS Scan — {market_status_msg()} ===")
    clear_cache()
    data = fetch_batch(get_idx_tickers(), interval="5m")
    candidates = []
    reject_counter = Counter()

    for ticker, (df_i, df_d) in data.items():
        if df_i is None or df_d is None:
            reject_counter["no_data"] += 1
            continue
        ok, reason = _filter_bpjs(df_i, df_d)
        if not ok:
            # Ambil gate prefix saja untuk grouping
            gate = reason.split(":")[0] if ":" in reason else reason
            reject_counter[gate] += 1
            continue
        candidates.append(_build(ticker, df_i, df_d, "BPJS"))

    # Log reject summary — sangat berguna untuk diagnosa
    total_valid = sum(reject_counter.values()) + len(candidates)
    logger.info(f"BPJS REJECT SUMMARY (dari {total_valid} ticker valid):")
    for reason, count in reject_counter.most_common():
        logger.info(f"  {reason}: {count} ticker")
    logger.info(f"BPJS: {len(candidates)} lolos | {total_valid} valid ticker")

    candidates.sort(key=_sort_key, reverse=True)
    return candidates[:top_n]


def run_bsjp_scan(top_n: int = None) -> List[StockCandidate]:
    if top_n is None: top_n = settings.TOP_N_RESULTS
    logger.info(f"=== BSJP Scan — {market_status_msg()} ===")
    clear_cache()
    data = fetch_batch(get_idx_tickers(), interval="15m")
    candidates = []
    reject_counter = Counter()

    for ticker, (df_i, df_d) in data.items():
        if df_i is None or df_d is None:
            reject_counter["no_data"] += 1
            continue
        ok, reason = _filter_bsjp(df_i, df_d)
        if not ok:
            gate = reason.split(":")[0] if ":" in reason else reason
            reject_counter[gate] += 1
            continue
        candidates.append(_build(ticker, df_i, df_d, "BSJP"))

    logger.info(f"BSJP REJECT SUMMARY:")
    for reason, count in reject_counter.most_common():
        logger.info(f"  {reason}: {count} ticker")
    logger.info(f"BSJP: {len(candidates)} lolos")

    candidates.sort(key=_sort_key, reverse=True)
    return candidates[:top_n]


def run_full_scan(top_n: int = None) -> Dict[str, List[StockCandidate]]:
    return {"bpjs": run_bpjs_scan(top_n), "bsjp": run_bsjp_scan(top_n)}


def run_combined_top_scan(top_n: int = None):
    return run_bpjs_scan(top_n), run_bsjp_scan(top_n)

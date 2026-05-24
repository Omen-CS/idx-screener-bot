"""
screener/scoring.py
Scoring engine for BPJS and BSJP scanner modes.

Each mode has its own scoring rubric based on weighted signals.
Final score is 0-100. Higher = stronger setup.
"""

import logging
from typing import Dict, Tuple, List

from config import settings

logger = logging.getLogger(__name__)


def score_bpjs(signals: Dict[str, bool]) -> Tuple[int, List[str]]:
    """
    Scores a stock for the BPJS (intraday morning) scanner.

    Scoring rubric:
    +25 Volume Explosion (rel vol > 3x)
    +25 Breakout Strength (breaks morning high + price moving)
    +20 Bullish Structure (bullish candle + higher low + no big wick)
    +15 Above VWAP
    +15 Momentum Continuation (above EMA20 + RSI not overbought)

    Args:
        signals: Dictionary of signal name → bool from patterns.get_signal_flags()

    Returns:
        Tuple[int, List[str]]: (total_score, list_of_triggered_signal_labels)
    """
    score = 0
    triggered: List[str] = []

    # --- Volume Explosion (+25) ---
    if signals.get("volume_explosion", False):
        score += settings.BPJS_SCORE_VOLUME_EXPLOSION
        triggered.append("Volume Explosion")

    # --- Breakout Strength (+25) ---
    breakout_score = 0
    if signals.get("breaks_morning_high", False):
        breakout_score += 15
    if signals.get("price_moving", False):
        breakout_score += 10
    if breakout_score > 0:
        # Scale to max 25 pts
        actual = int((breakout_score / 25) * settings.BPJS_SCORE_BREAKOUT_STRENGTH)
        score += actual
        if signals.get("breaks_morning_high", False):
            triggered.append("Morning Breakout")

    # --- Bullish Structure (+20) ---
    struct_score = 0
    if signals.get("bullish_candle", False):
        struct_score += 8
    if signals.get("higher_low", False):
        struct_score += 7
    if signals.get("no_big_upper_wick", False):
        struct_score += 5
    if struct_score >= 10:
        score += min(struct_score, settings.BPJS_SCORE_BULLISH_STRUCTURE)
        triggered.append("Bullish Structure")

    # --- Above VWAP (+15) ---
    if signals.get("above_vwap", False):
        score += settings.BPJS_SCORE_ABOVE_VWAP
        triggered.append("Above VWAP")

    # --- Momentum Continuation (+15) ---
    mom_score = 0
    if signals.get("above_ema20", False):
        mom_score += 8
    if signals.get("rsi_not_overbought", False):
        mom_score += 7
    if mom_score >= 8:
        score += min(mom_score, settings.BPJS_SCORE_MOMENTUM_CONTINUATION)
        triggered.append("Bullish Momentum")

    # --- Penalties ---
    # Illiquid stock
    if not signals.get("sufficient_liquidity", True):
        score = max(0, score - 20)

    # Pump and dump detected
    if not signals.get("no_pump_dump", True):
        score = max(0, score - 30)

    return min(score, 100), triggered


def score_bsjp(signals: Dict[str, bool]) -> Tuple[int, List[str]]:
    """
    Scores a stock for the BSJP (afternoon close) scanner.

    Scoring rubric:
    +30 Strong Close (close near high + small upper wick)
    +25 Breakout Quality (breaks resistance)
    +20 Accumulation Volume (strong last hour + accumulation pattern)
    +15 Bullish Trend (EMA bullish structure + higher low)
    +10 Low Selling Pressure (no panic selling + bullish candle)

    Args:
        signals: Dictionary of signal name → bool from patterns.get_signal_flags()

    Returns:
        Tuple[int, List[str]]: (total_score, list_of_triggered_signal_labels)
    """
    score = 0
    triggered: List[str] = []

    # --- Strong Close (+30) ---
    close_score = 0
    if signals.get("close_near_high", False):
        close_score += 20
        triggered.append("Strong Close")
    if signals.get("small_upper_wick", False):
        close_score += 10
    score += min(close_score, settings.BSJP_SCORE_STRONG_CLOSE)

    # --- Breakout Quality (+25) ---
    if signals.get("breaks_resistance", False):
        score += settings.BSJP_SCORE_BREAKOUT_QUALITY
        triggered.append("Resistance Breakout")

    # --- Accumulation Volume (+20) ---
    accum_score = 0
    if signals.get("strong_last_hour", False):
        accum_score += 12
    if signals.get("accumulation", False):
        accum_score += 8
        triggered.append("Afternoon Accumulation")
    score += min(accum_score, settings.BSJP_SCORE_ACCUMULATION_VOLUME)

    # --- Bullish Trend (+15) ---
    trend_score = 0
    if signals.get("ema_bullish", False):
        trend_score += 8
    if signals.get("higher_low", False):
        trend_score += 7
    if trend_score >= 8:
        score += min(trend_score, settings.BSJP_SCORE_BULLISH_TREND)
        triggered.append("Bullish Structure")

    # --- Low Selling Pressure (+10) ---
    selling_score = 0
    if signals.get("no_panic_selling", False):
        selling_score += 5
    if signals.get("bullish_candle", False):
        selling_score += 5
    score += min(selling_score, settings.BSJP_SCORE_LOW_SELLING_PRESSURE)

    # --- Penalties ---
    if not signals.get("sufficient_liquidity", True):
        score = max(0, score - 15)

    return min(score, 100), triggered


def passes_bpjs_filter(signals: Dict[str, bool]) -> bool:
    """
    Hard filter: stock must pass these conditions to even be scored for BPJS.

    Returns:
        bool: True if stock passes basic BPJS requirements
    """
    # Must have minimum liquidity
    if not signals.get("sufficient_liquidity", False):
        return False

    # Must not be a pump-and-dump
    if not signals.get("no_pump_dump", True):
        return False

    # Must have some volume explosion
    if not signals.get("volume_explosion", False):
        return False

    return True


def passes_bsjp_filter(signals: Dict[str, bool]) -> bool:
    """
    Hard filter: stock must pass these conditions to even be scored for BSJP.

    Returns:
        bool: True if stock passes basic BSJP requirements
    """
    # Must have minimum liquidity
    if not signals.get("sufficient_liquidity", False):
        return False

    # Must not have panic selling
    if not signals.get("no_panic_selling", True):
        return False

    # Must have closed near the high
    if not signals.get("close_near_high", False):
        return False

    return True

"""
screener/patterns.py
Market structure and candlestick pattern detection for the IDX screener.

These functions analyze price action patterns beyond basic indicators.
"""

import logging
import pandas as pd
import numpy as np
from typing import Dict

logger = logging.getLogger(__name__)


def detect_ema_bullish_structure(df: pd.DataFrame) -> bool:
    """
    Detects bullish EMA structure: price above EMA20, EMA20 trending up.

    Args:
        df: OHLCV dataframe with enough candles for EMA20

    Returns:
        bool: True if bullish EMA structure confirmed
    """
    if len(df) < 25:
        return False

    from screener.indicators import ema20
    ema_series = ema20(df)

    current_price = df["Close"].iloc[-1]
    current_ema = ema_series.iloc[-1]
    prev_ema = ema_series.iloc[-3]  # 3 candles ago

    # Price above EMA20 AND EMA20 trending up
    price_above_ema = current_price > current_ema
    ema_trending_up = current_ema > prev_ema

    return price_above_ema and ema_trending_up


def detect_accumulation_pattern(df_intraday: pd.DataFrame) -> bool:
    """
    Detects afternoon accumulation pattern for BSJP mode.

    Signs of accumulation:
    - Volume increasing in last few candles
    - Price holding steady or moving up on volume
    - No large selling candles

    Args:
        df_intraday: Intraday data (last session)

    Returns:
        bool: True if accumulation pattern detected
    """
    if len(df_intraday) < 8:
        return False

    # Check last 4 candles
    recent = df_intraday.tail(4)

    # Volume increasing trend in recent candles
    vols = recent["Volume"].values
    vol_increasing = sum(1 for i in range(1, len(vols)) if vols[i] >= vols[i - 1])
    vol_trend_up = vol_increasing >= 2

    # Price not dropping — close of last candle >= open of first recent candle
    price_holding = recent["Close"].iloc[-1] >= recent["Open"].iloc[0]

    # No large red candles (dump candles) — body shouldn't be > 2% down
    no_dump_candles = True
    for _, row in recent.iterrows():
        if row["Open"] > 0:
            pct_move = (row["Close"] - row["Open"]) / row["Open"] * 100
            if pct_move < -2.0:
                no_dump_candles = False
                break

    return vol_trend_up and price_holding and no_dump_candles


def detect_pump_and_dump(df_intraday: pd.DataFrame) -> bool:
    """
    Detects obvious pump-and-dump signals to AVOID.

    Signs:
    - Huge spike candle followed by immediate reversal
    - Volume spike then complete dryup
    - Price now below VWAP significantly after a spike

    Args:
        df_intraday: Intraday data

    Returns:
        bool: True if pump-and-dump pattern suspected (should EXCLUDE)
    """
    if len(df_intraday) < 6:
        return False

    from screener.indicators import vwap, get_current_price

    # Check for price spike then collapse
    rolling_high = df_intraday["High"].max()
    current_price = get_current_price(df_intraday)

    if rolling_high > 0 and current_price < rolling_high * 0.85:
        # Price dropped more than 15% from day high = potential dump
        return True

    # Check for extreme volume spike at start, then dry up
    first_half = df_intraday.iloc[: len(df_intraday) // 2]["Volume"].mean()
    second_half = df_intraday.iloc[len(df_intraday) // 2 :]["Volume"].mean()

    if first_half > 0 and second_half < first_half * 0.2:
        # Second half volume is less than 20% of first half = volume dried up
        return True

    return False


def detect_choppy_structure(df: pd.DataFrame, lookback: int = 8) -> bool:
    """
    Detects choppy, sideways price action with no clear direction.

    Args:
        df: OHLCV dataframe
        lookback: Candles to analyze

    Returns:
        bool: True if choppy (should lower score or exclude)
    """
    if len(df) < lookback:
        return False

    recent = df.tail(lookback)

    # Calculate directional movement
    closes = recent["Close"].values
    direction_changes = sum(
        1 for i in range(1, len(closes) - 1)
        if (closes[i] - closes[i - 1]) * (closes[i + 1] - closes[i]) < 0
    )

    # More than half the candles changing direction = choppy
    return direction_changes > lookback * 0.5


def detect_panic_selling(df_intraday: pd.DataFrame) -> bool:
    """
    Detects panic selling in last few candles for BSJP exclusion.

    Signs:
    - Large red candles in last 3 candles
    - Increasing volume on down moves

    Args:
        df_intraday: Intraday data

    Returns:
        bool: True if panic selling detected
    """
    if len(df_intraday) < 4:
        return False

    recent = df_intraday.tail(3)
    red_candles = sum(1 for _, row in recent.iterrows() if row["Close"] < row["Open"])

    # 2 or 3 of last 3 candles are red = selling pressure
    if red_candles >= 2:
        # Check if volume is increasing on those red candles
        red_vols = [
            row["Volume"] for _, row in recent.iterrows()
            if row["Close"] < row["Open"]
        ]
        if red_vols and sum(red_vols) / len(red_vols) > df_intraday["Volume"].mean():
            return True

    return False


def get_signal_flags(
    ticker: str,
    df_intraday: pd.DataFrame,
    df_daily: pd.DataFrame,
    mode: str,
) -> Dict[str, bool]:
    """
    Returns a dictionary of all signal flags for a given ticker and mode.

    Args:
        ticker: Stock ticker symbol
        df_intraday: Intraday OHLCV data
        df_daily: Daily OHLCV data
        mode: 'BPJS' or 'BSJP'

    Returns:
        Dict[str, bool]: Signal name → True/False
    """
    from screener import indicators as ind

    flags: Dict[str, bool] = {}

    try:
        current_price = ind.get_current_price(df_intraday)
        ema20_val = ind.get_ema20_value(df_intraday)
        vwap_val = ind.get_vwap_value(df_intraday)
        rsi_val = ind.get_rsi_value(df_intraday)
        rel_vol = ind.relative_volume(df_intraday, df_daily)
        price_move = ind.price_change_pct_from_open(df_intraday)
        traded_val = ind.traded_value_idr(df_intraday)

        if mode == "BPJS":
            flags["volume_explosion"] = rel_vol >= 3.0
            flags["price_moving"] = 2.0 <= price_move <= 7.0
            flags["breaks_morning_high"] = ind.is_breaking_morning_high(df_intraday, 6)
            flags["bullish_candle"] = ind.is_bullish_candle(df_intraday.iloc[-1])
            flags["higher_low"] = ind.detect_higher_low(df_intraday, 5)
            flags["above_ema20"] = current_price > ema20_val > 0
            flags["above_vwap"] = current_price > vwap_val > 0
            flags["sufficient_liquidity"] = traded_val >= 1_000_000_000
            flags["rsi_not_overbought"] = rsi_val < 85.0
            flags["no_pump_dump"] = not detect_pump_and_dump(df_intraday)

            # Wick check — avoid huge upper wicks
            last_candle = df_intraday.iloc[-1]
            flags["no_big_upper_wick"] = ind.upper_wick_ratio(last_candle) < 0.40

        elif mode == "BSJP":
            flags["close_near_high"] = ind.close_near_high_ratio(df_intraday) >= 0.92
            flags["strong_last_hour"] = ind.last_hour_volume_ratio(df_intraday, 4) >= 1.5
            flags["breaks_resistance"] = ind.is_breaking_resistance(df_daily, 20)
            flags["higher_low"] = ind.detect_higher_low(df_intraday, 5)
            flags["ema_bullish"] = detect_ema_bullish_structure(df_daily)
            flags["bullish_candle"] = ind.is_bullish_candle(df_intraday.iloc[-1])
            flags["accumulation"] = detect_accumulation_pattern(df_intraday)
            flags["no_panic_selling"] = not detect_panic_selling(df_intraday)

            last_candle = df_intraday.iloc[-1]
            flags["small_upper_wick"] = ind.upper_wick_ratio(last_candle) < 0.30
            flags["sufficient_liquidity"] = traded_val >= 500_000_000

    except Exception as e:
        logger.debug(f"Signal detection error for {ticker}: {e}")

    return flags

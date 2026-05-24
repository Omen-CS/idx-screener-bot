"""
screener/indicators.py
Technical indicator calculations for the IDX screener.

All functions accept a pandas DataFrame with OHLCV columns:
    Open, High, Low, Close, Volume

Returns Series or scalar values.
Uses the 'ta' library plus manual calculations where needed.
"""

import logging
import numpy as np
import pandas as pd
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Moving Averages
# ---------------------------------------------------------------------------

def ema(series: pd.Series, period: int) -> pd.Series:
    """
    Exponential Moving Average.

    Args:
        series: Price series (typically Close)
        period: EMA period

    Returns:
        pd.Series: EMA values
    """
    return series.ewm(span=period, adjust=False).mean()


def ema20(df: pd.DataFrame) -> pd.Series:
    """EMA with period 20."""
    return ema(df["Close"], 20)


def ema50(df: pd.DataFrame) -> pd.Series:
    """EMA with period 50."""
    return ema(df["Close"], 50)


# ---------------------------------------------------------------------------
# RSI
# ---------------------------------------------------------------------------

def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """
    Relative Strength Index using Wilder's smoothing method.

    Args:
        series: Price series
        period: RSI lookback period (default 14)

    Returns:
        pd.Series: RSI values 0–100
    """
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi_val = 100 - (100 / (1 + rs))
    return rsi_val


# ---------------------------------------------------------------------------
# VWAP
# ---------------------------------------------------------------------------

def vwap(df: pd.DataFrame) -> pd.Series:
    """
    Volume Weighted Average Price (VWAP).
    Calculated as cumulative (Typical Price × Volume) / cumulative Volume.

    Args:
        df: DataFrame with High, Low, Close, Volume columns

    Returns:
        pd.Series: VWAP values
    """
    typical_price = (df["High"] + df["Low"] + df["Close"]) / 3
    cum_tp_vol = (typical_price * df["Volume"]).cumsum()
    cum_vol = df["Volume"].cumsum()
    return cum_tp_vol / cum_vol.replace(0, np.nan)


# ---------------------------------------------------------------------------
# Relative Volume
# ---------------------------------------------------------------------------

def relative_volume(df_intraday: pd.DataFrame, df_daily: pd.DataFrame) -> float:
    """
    Relative volume: today's volume vs 5-day average daily volume.

    Args:
        df_intraday: Intraday OHLCV data for today
        df_daily: Daily OHLCV data (last 10+ days)

    Returns:
        float: Relative volume ratio (e.g. 3.5 = 3.5x average)
    """
    try:
        today_volume = df_intraday["Volume"].sum()

        # Use last 5 days of daily data (excluding today if present)
        daily_vols = df_daily["Volume"].tail(10)
        if len(daily_vols) < 3:
            return 1.0

        avg_volume = daily_vols.mean()
        if avg_volume <= 0:
            return 1.0

        return today_volume / avg_volume
    except Exception as e:
        logger.debug(f"relative_volume error: {e}")
        return 1.0


# ---------------------------------------------------------------------------
# Candle Structure Analysis
# ---------------------------------------------------------------------------

def candle_body_ratio(row: pd.Series) -> float:
    """
    Ratio of candle body to full candle range.
    High body ratio = strong directional move.

    Args:
        row: Single candle row with Open, High, Low, Close

    Returns:
        float: 0.0 to 1.0 (1.0 = no wicks, pure body)
    """
    candle_range = row["High"] - row["Low"]
    if candle_range <= 0:
        return 0.0
    body = abs(row["Close"] - row["Open"])
    return body / candle_range


def upper_wick_ratio(row: pd.Series) -> float:
    """
    Ratio of upper wick to full candle range.
    High ratio = selling pressure at top = bearish sign.

    Args:
        row: Single candle row with Open, High, Low, Close

    Returns:
        float: 0.0 to 1.0
    """
    candle_range = row["High"] - row["Low"]
    if candle_range <= 0:
        return 0.0
    upper_wick = row["High"] - max(row["Open"], row["Close"])
    return max(0.0, upper_wick / candle_range)


def lower_wick_ratio(row: pd.Series) -> float:
    """
    Ratio of lower wick to full candle range.

    Args:
        row: Single candle row with Open, High, Low, Close

    Returns:
        float: 0.0 to 1.0
    """
    candle_range = row["High"] - row["Low"]
    if candle_range <= 0:
        return 0.0
    lower_wick = min(row["Open"], row["Close"]) - row["Low"]
    return max(0.0, lower_wick / candle_range)


def is_bullish_candle(row: pd.Series) -> bool:
    """Returns True if candle closes higher than it opened."""
    return row["Close"] > row["Open"]


# ---------------------------------------------------------------------------
# Breakout Detection
# ---------------------------------------------------------------------------

def morning_high(df_intraday: pd.DataFrame, morning_candles: int = 6) -> float:
    """
    Returns the high of the first N candles (morning range).
    For 5m data, 6 candles = first 30 minutes.

    Args:
        df_intraday: Intraday data sorted ascending by time
        morning_candles: Number of opening candles to define morning range

    Returns:
        float: Morning session high price
    """
    if len(df_intraday) < morning_candles:
        return df_intraday["High"].max()
    return df_intraday["High"].iloc[:morning_candles].max()


def is_breaking_morning_high(df_intraday: pd.DataFrame, morning_candles: int = 6) -> bool:
    """
    Returns True if the latest candle breaks above morning high.

    Args:
        df_intraday: Intraday data sorted ascending
        morning_candles: Candles used to define morning high

    Returns:
        bool: True if current price > morning high
    """
    if len(df_intraday) < morning_candles + 1:
        return False

    m_high = morning_high(df_intraday, morning_candles)
    current_high = df_intraday["High"].iloc[-1]
    return current_high > m_high


def detect_higher_low(df: pd.DataFrame, lookback: int = 5) -> bool:
    """
    Detects higher low structure in recent candles.
    Checks if recent lows form an ascending pattern.

    Args:
        df: OHLCV dataframe
        lookback: Number of recent candles to check

    Returns:
        bool: True if higher low structure detected
    """
    if len(df) < lookback + 1:
        return False

    recent_lows = df["Low"].tail(lookback + 1).values
    # At least half the consecutive pairs must show higher lows
    higher_low_count = sum(
        1 for i in range(1, len(recent_lows))
        if recent_lows[i] > recent_lows[i - 1]
    )
    return higher_low_count >= (lookback // 2)


def resistance_level(df_daily: pd.DataFrame, lookback: int = 20) -> float:
    """
    Calculates recent resistance as the highest high over lookback days.

    Args:
        df_daily: Daily OHLCV data
        lookback: Days to look back

    Returns:
        float: Resistance price level
    """
    if len(df_daily) < 2:
        return df_daily["High"].max()
    # Exclude today's candle when calculating historical resistance
    return df_daily["High"].iloc[:-1].tail(lookback).max()


def is_breaking_resistance(df_daily: pd.DataFrame, lookback: int = 20) -> bool:
    """
    Returns True if today's price breaks above recent resistance.

    Args:
        df_daily: Daily OHLCV data
        lookback: Days for resistance calculation

    Returns:
        bool: True if breakout detected
    """
    if len(df_daily) < 3:
        return False

    resist = resistance_level(df_daily, lookback)
    current_close = df_daily["Close"].iloc[-1]
    return current_close > resist


# ---------------------------------------------------------------------------
# Volume Helpers
# ---------------------------------------------------------------------------

def traded_value_idr(df_intraday: pd.DataFrame) -> float:
    """
    Total traded value in IDR for the current session.
    Approximates: sum(Close * Volume) across all intraday candles.

    Args:
        df_intraday: Intraday OHLCV data

    Returns:
        float: Approximate traded value in IDR
    """
    return (df_intraday["Close"] * df_intraday["Volume"]).sum()


def last_hour_volume_ratio(df_intraday: pd.DataFrame, candles_per_hour: int = 4) -> float:
    """
    Ratio of last N candles volume to session average candle volume.
    Used by BSJP to detect afternoon accumulation.

    Args:
        df_intraday: Full intraday data
        candles_per_hour: Candles in one hour (4 for 15m data, 12 for 5m)

    Returns:
        float: Ratio (>1 = above average, <1 = below average)
    """
    if len(df_intraday) < candles_per_hour + 2:
        return 1.0

    session_avg = df_intraday["Volume"].mean()
    if session_avg <= 0:
        return 1.0

    last_hour_avg = df_intraday["Volume"].tail(candles_per_hour).mean()
    return last_hour_avg / session_avg


# ---------------------------------------------------------------------------
# Price Change Helpers
# ---------------------------------------------------------------------------

def price_change_pct_from_open(df_intraday: pd.DataFrame) -> float:
    """
    Percentage change from session open to current price.

    Args:
        df_intraday: Intraday data sorted ascending

    Returns:
        float: Percentage change (e.g. 3.5 = +3.5%)
    """
    if len(df_intraday) < 2:
        return 0.0

    open_price = df_intraday["Open"].iloc[0]
    current_price = df_intraday["Close"].iloc[-1]

    if open_price <= 0:
        return 0.0

    return ((current_price - open_price) / open_price) * 100


def close_near_high_ratio(df_intraday: pd.DataFrame) -> float:
    """
    Ratio of close price to day high.
    1.0 = closed exactly at high (very bullish).
    0.5 = closed at midpoint of day range.

    Args:
        df_intraday: Intraday data

    Returns:
        float: Ratio 0.0 to 1.0
    """
    day_high = df_intraday["High"].max()
    day_low = df_intraday["Low"].min()
    current_close = df_intraday["Close"].iloc[-1]

    day_range = day_high - day_low
    if day_range <= 0:
        return 1.0

    return (current_close - day_low) / day_range


def get_current_price(df_intraday: pd.DataFrame) -> float:
    """Returns the most recent closing price."""
    if df_intraday.empty:
        return 0.0
    return float(df_intraday["Close"].iloc[-1])


def get_ema20_value(df_intraday: pd.DataFrame) -> float:
    """Returns the most recent EMA20 value."""
    if len(df_intraday) < 5:
        return 0.0
    return float(ema20(df_intraday).iloc[-1])


def get_vwap_value(df_intraday: pd.DataFrame) -> float:
    """Returns the most recent VWAP value."""
    if df_intraday.empty:
        return 0.0
    return float(vwap(df_intraday).iloc[-1])


def get_rsi_value(df_intraday: pd.DataFrame) -> float:
    """Returns the most recent RSI(14) value."""
    if len(df_intraday) < 15:
        return 50.0  # Neutral default
    return float(rsi(df_intraday["Close"]).iloc[-1])

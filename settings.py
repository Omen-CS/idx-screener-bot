"""
config/settings.py
Centralized configuration for the IDX Stock Screener Bot.
All tunable parameters live here.
"""

import os
import pytz
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# ---------------------------------------------------------------------------
# Telegram
# ---------------------------------------------------------------------------
TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")

# ---------------------------------------------------------------------------
# Timezone
# ---------------------------------------------------------------------------
WIB = pytz.timezone("Asia/Jakarta")

# ---------------------------------------------------------------------------
# Scheduler — times in WIB (24h)
# ---------------------------------------------------------------------------
BPJS_HOUR: int = 9
BPJS_MINUTE: int = 0

BSJP_HOUR: int = 14
BSJP_MINUTE: int = 0

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
LOG_FILE: str = "logs/screener.log"

# ---------------------------------------------------------------------------
# Market Data
# ---------------------------------------------------------------------------
# Interval for intraday data (BPJS uses 5m, BSJP uses 15m)
BPJS_INTERVAL: str = "5m"
BSJP_INTERVAL: str = "15m"

# Period for daily data used in trend calculations
DAILY_PERIOD: str = "30d"

# Period for intraday data
INTRADAY_PERIOD: str = "1d"

# Batch size when fetching tickers to avoid rate limits
TICKER_BATCH_SIZE: int = 20

# Seconds to sleep between batches
BATCH_SLEEP_SECONDS: float = 2.0

# ---------------------------------------------------------------------------
# Screener Thresholds — BPJS (Intraday Morning)
# ---------------------------------------------------------------------------
BPJS_MIN_RELATIVE_VOLUME: float = 3.0       # Relative volume vs 5-day avg
BPJS_MIN_PRICE_MOVE_PCT: float = 2.0        # Minimum % price move since open
BPJS_MAX_PRICE_MOVE_PCT: float = 7.0        # Maximum % move (avoid chasing)
BPJS_MIN_TRADED_VALUE_IDR: float = 1_000_000_000  # 1 Billion IDR minimum
BPJS_MAX_RSI: float = 85.0                  # Avoid overbought extremes
BPJS_MAX_UPPER_WICK_RATIO: float = 0.40     # Upper wick / candle range ratio

# ---------------------------------------------------------------------------
# Screener Thresholds — BSJP (Afternoon Close)
# ---------------------------------------------------------------------------
BSJP_CLOSE_NEAR_HIGH_RATIO: float = 0.92   # Close must be >= 92% of day high
BSJP_MIN_LAST_HOUR_VOL_RATIO: float = 1.5  # Last hour vol vs session avg
BSJP_MAX_UPPER_WICK_RATIO: float = 0.30    # Tighter wick filter for EOD
BSJP_MIN_TRADED_VALUE_IDR: float = 500_000_000  # 500M IDR minimum

# ---------------------------------------------------------------------------
# General Screener
# ---------------------------------------------------------------------------
MIN_PRICE_IDR: float = 50.0        # Skip penny stocks below 50 IDR
MAX_PRICE_IDR: float = 50_000.0    # Skip extremely high-priced stocks
TOP_N_RESULTS: int = 10            # Number of results returned by /top

# ---------------------------------------------------------------------------
# Scoring Weights — BPJS
# ---------------------------------------------------------------------------
BPJS_SCORE_VOLUME_EXPLOSION: int = 25
BPJS_SCORE_BREAKOUT_STRENGTH: int = 25
BPJS_SCORE_BULLISH_STRUCTURE: int = 20
BPJS_SCORE_ABOVE_VWAP: int = 15
BPJS_SCORE_MOMENTUM_CONTINUATION: int = 15

# ---------------------------------------------------------------------------
# Scoring Weights — BSJP
# ---------------------------------------------------------------------------
BSJP_SCORE_STRONG_CLOSE: int = 30
BSJP_SCORE_BREAKOUT_QUALITY: int = 25
BSJP_SCORE_ACCUMULATION_VOLUME: int = 20
BSJP_SCORE_BULLISH_TREND: int = 15
BSJP_SCORE_LOW_SELLING_PRESSURE: int = 10

# ---------------------------------------------------------------------------
# Minimum score threshold to include in alert
# ---------------------------------------------------------------------------
MIN_SCORE_THRESHOLD: int = 50

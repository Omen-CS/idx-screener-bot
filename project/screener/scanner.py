"""
screener/scanner.py
Main scanner orchestration module.

Coordinates:
1. Ticker fetching
2. Market data downloading (batched)
3. Signal detection
4. Scoring
5. Filtering
6. Ranking

Returns ranked list of momentum candidates for each mode.
"""

import logging
from dataclasses import dataclass, field
from typing import List, Optional, Dict

from config import settings
from screener.tickers import get_idx_tickers
from screener.patterns import get_signal_flags
from screener.scoring import (
    score_bpjs,
    score_bsjp,
    passes_bpjs_filter,
    passes_bsjp_filter,
)
from screener import indicators as ind
from services.market_data import fetch_batch, clear_cache

logger = logging.getLogger(__name__)


@dataclass
class StockCandidate:
    """Represents a single screened stock candidate."""
    ticker: str
    score: int
    price: float
    mode: str                          # 'BPJS' or 'BSJP'
    signals_triggered: List[str] = field(default_factory=list)
    rel_volume: float = 0.0
    price_change_pct: float = 0.0
    rsi: float = 50.0
    traded_value_idr: float = 0.0

    def to_dict(self) -> Dict:
        return {
            "ticker": self.ticker,
            "score": self.score,
            "price": self.price,
            "mode": self.mode,
            "signals": self.signals_triggered,
            "rel_volume": self.rel_volume,
            "price_change_pct": self.price_change_pct,
            "rsi": self.rsi,
            "traded_value_idr": self.traded_value_idr,
        }


def run_bpjs_scan(top_n: int = None) -> List[StockCandidate]:
    """
    Runs the BPJS (Beli Pagi Jual Sore) morning scanner.

    Finds intraday momentum continuation setups.

    Args:
        top_n: Maximum number of results to return

    Returns:
        List[StockCandidate]: Ranked candidates, best score first
    """
    if top_n is None:
        top_n = settings.TOP_N_RESULTS

    logger.info("=== Starting BPJS Scan ===")

    # Clear stale cache before scan
    clear_cache()

    tickers = get_idx_tickers()
    logger.info(f"Scanning {len(tickers)} tickers for BPJS setups")

    # Fetch all data in batches
    data = fetch_batch(
        tickers,
        interval=settings.BPJS_INTERVAL,
        batch_size=settings.TICKER_BATCH_SIZE,
        sleep_between_batches=settings.BATCH_SLEEP_SECONDS,
    )

    candidates: List[StockCandidate] = []
    scanned = 0
    passed_filter = 0
    errors = 0

    for ticker, (df_intraday, df_daily) in data.items():
        try:
            # Skip if no data
            if df_intraday is None or df_daily is None:
                continue
            if df_intraday.empty or df_daily.empty:
                continue
            if len(df_intraday) < 5:
                continue

            # Basic price filter
            current_price = ind.get_current_price(df_intraday)
            if not (settings.MIN_PRICE_IDR <= current_price <= settings.MAX_PRICE_IDR):
                continue

            scanned += 1

            # Get all signal flags
            signals = get_signal_flags(ticker, df_intraday, df_daily, mode="BPJS")

            # Apply hard filter — must pass basic criteria
            if not passes_bpjs_filter(signals):
                continue

            passed_filter += 1

            # Score the stock
            score, triggered = score_bpjs(signals)

            # Minimum score threshold
            if score < settings.MIN_SCORE_THRESHOLD:
                continue

            # Build candidate object
            candidate = StockCandidate(
                ticker=ticker,
                score=score,
                price=current_price,
                mode="BPJS",
                signals_triggered=triggered,
                rel_volume=ind.relative_volume(df_intraday, df_daily),
                price_change_pct=ind.price_change_pct_from_open(df_intraday),
                rsi=ind.get_rsi_value(df_intraday),
                traded_value_idr=ind.traded_value_idr(df_intraday),
            )
            candidates.append(candidate)

        except Exception as e:
            errors += 1
            logger.debug(f"Error processing {ticker} for BPJS: {e}")

    # Sort by score descending
    candidates.sort(key=lambda x: x.score, reverse=True)

    logger.info(
        f"BPJS Scan complete: {scanned} scanned, {passed_filter} passed filter, "
        f"{len(candidates)} scored above threshold, {errors} errors"
    )

    return candidates[:top_n]


def run_bsjp_scan(top_n: int = None) -> List[StockCandidate]:
    """
    Runs the BSJP (Beli Sore Jual Pagi) afternoon scanner.

    Finds strong closing stocks likely to continue next morning.

    Args:
        top_n: Maximum number of results to return

    Returns:
        List[StockCandidate]: Ranked candidates, best score first
    """
    if top_n is None:
        top_n = settings.TOP_N_RESULTS

    logger.info("=== Starting BSJP Scan ===")

    # Clear stale cache before scan
    clear_cache()

    tickers = get_idx_tickers()
    logger.info(f"Scanning {len(tickers)} tickers for BSJP setups")

    # BSJP uses 15m intervals for better signal quality
    data = fetch_batch(
        tickers,
        interval=settings.BSJP_INTERVAL,
        batch_size=settings.TICKER_BATCH_SIZE,
        sleep_between_batches=settings.BATCH_SLEEP_SECONDS,
    )

    candidates: List[StockCandidate] = []
    scanned = 0
    passed_filter = 0
    errors = 0

    for ticker, (df_intraday, df_daily) in data.items():
        try:
            # Skip if no data
            if df_intraday is None or df_daily is None:
                continue
            if df_intraday.empty or df_daily.empty:
                continue
            if len(df_intraday) < 4:
                continue

            # Basic price filter
            current_price = ind.get_current_price(df_intraday)
            if not (settings.MIN_PRICE_IDR <= current_price <= settings.MAX_PRICE_IDR):
                continue

            scanned += 1

            # Get all signal flags
            signals = get_signal_flags(ticker, df_intraday, df_daily, mode="BSJP")

            # Apply hard filter — must pass basic criteria
            if not passes_bsjp_filter(signals):
                continue

            passed_filter += 1

            # Score the stock
            score, triggered = score_bsjp(signals)

            # Minimum score threshold
            if score < settings.MIN_SCORE_THRESHOLD:
                continue

            # Build candidate object
            candidate = StockCandidate(
                ticker=ticker,
                score=score,
                price=current_price,
                mode="BSJP",
                signals_triggered=triggered,
                rel_volume=ind.relative_volume(df_intraday, df_daily),
                price_change_pct=ind.price_change_pct_from_open(df_intraday),
                rsi=ind.get_rsi_value(df_intraday),
                traded_value_idr=ind.traded_value_idr(df_intraday),
            )
            candidates.append(candidate)

        except Exception as e:
            errors += 1
            logger.debug(f"Error processing {ticker} for BSJP: {e}")

    # Sort by score descending
    candidates.sort(key=lambda x: x.score, reverse=True)

    logger.info(
        f"BSJP Scan complete: {scanned} scanned, {passed_filter} passed filter, "
        f"{len(candidates)} scored above threshold, {errors} errors"
    )

    return candidates[:top_n]


def run_full_scan(top_n: int = None) -> Dict[str, List[StockCandidate]]:
    """
    Runs both BPJS and BSJP scans.
    Used by the /scan command.

    Args:
        top_n: Max results per mode

    Returns:
        Dict with 'bpjs' and 'bsjp' keys
    """
    return {
        "bpjs": run_bpjs_scan(top_n),
        "bsjp": run_bsjp_scan(top_n),
    }

def run_combined_top_scan(top_n: int = None) -> tuple[List[StockCandidate], List[StockCandidate]]:
    """
    Menjalankan scan gabungan BPJS dan BSJP sekaligus dalam 1x download data
    untuk menghemat waktu dan mencegah timeout di perintah /top.
    """
    if top_n is None:
        top_n = settings.TOP_N_RESULTS

    logger.info("=== Starting Combined Top Scan (Optimized) ===")
    clear_cache()

    tickers = get_idx_tickers()
    logger.info(f"Scanning {len(tickers)} tickers for combined setups")

    # Ambil data cukup 1 KALI saja untuk kedua mode
    data = fetch_batch(
        tickers,
        interval=settings.BPJS_INTERVAL, # atau interval default yang mencakup data harian & intraday
        batch_size=settings.TICKER_BATCH_SIZE,
        sleep_between_batches=settings.BATCH_SLEEP_SECONDS,
    )

    bpjs_candidates: List[StockCandidate] = []
    bsjp_candidates: List[StockCandidate] = []

    for ticker, (df_intraday, df_daily) in data.items():
        try:
            if df_intraday is None or df_daily is None or df_intraday.empty or df_daily.empty:
                continue
            
            current_price = ind.get_current_price(df_intraday)
            if not (settings.MIN_PRICE_IDR <= current_price <= settings.MAX_PRICE_IDR):
                continue

            # --- PROSES BPJS ---
            signals_bpjs = get_signal_flags(ticker, df_intraday, df_daily, mode="BPJS")
            if passes_bpjs_filter(signals_bpjs):
                score_b, trig_b = score_bpjs(signals_bpjs)
                if score_b >= settings.MIN_SCORE_THRESHOLD:
                    bpjs_candidates.append(StockCandidate(
                        ticker=ticker, score=score_b, price=current_price, mode="BPJS",
                        signals_triggered=trig_b, rel_volume=ind.relative_volume(df_intraday, df_daily),
                        price_change_pct=ind.price_change_pct_from_open(df_intraday),
                        rsi=ind.get_rsi_value(df_intraday), traded_value_idr=ind.traded_value_idr(df_intraday)
                    ))

            # --- PROSES BSJP ---
            signals_bsjp = get_signal_flags(ticker, df_intraday, df_daily, mode="BSJP")
            if passes_bsjp_filter(signals_bsjp):
                score_s, trig_s = score_bsjp(signals_bsjp)
                if score_s >= settings.MIN_SCORE_THRESHOLD:
                    bsjp_candidates.append(StockCandidate(
                        ticker=ticker, score=score_s, price=current_price, mode="BSJP",
                        signals_triggered=trig_s, rel_volume=ind.relative_volume(df_intraday, df_daily),
                        price_change_pct=ind.price_change_pct_from_open(df_intraday),
                        rsi=ind.get_rsi_value(df_intraday), traded_value_idr=ind.traded_value_idr(df_intraday)
                    ))

        except Exception as e:
            logger.debug(f"Error filtering {ticker}: {e}")

    # Urutkan masing-masing
    bpjs_candidates.sort(key=lambda x: x.score, reverse=True)
    bsjp_candidates.sort(key=lambda x: x.score, reverse=True)

    return bpjs_candidates[:top_n], bsjp_candidates[:top_n]

"""
bot/utils/formatter.py
Formats scanner results into clean Telegram messages.

Handles:
- Individual stock alerts (BPJS / BSJP)
- Summary lists (/top command)
- No-result messages
- Error messages
"""

from typing import List
from screener.scanner import StockCandidate


def format_bpjs_alert(candidate: StockCandidate) -> str:
    """
    Formats a single BPJS candidate into a Telegram alert message.

    Args:
        candidate: StockCandidate with BPJS signals

    Returns:
        str: Formatted message text (Markdown compatible)
    """
    ticker_clean = candidate.ticker.replace(".JK", "")

    # Build signals section
    signal_lines = "\n".join(
        f"✅ {signal}" for signal in candidate.signals_triggered
    ) if candidate.signals_triggered else "⚠️ No strong signals"

    # Format price nicely
    price_str = f"{candidate.price:,.0f}"

    # Format relative volume
    rvol_str = f"{candidate.rel_volume:.1f}x"

    # Format price change
    change_sign = "+" if candidate.price_change_pct >= 0 else ""
    change_str = f"{change_sign}{candidate.price_change_pct:.1f}%"

    # Format traded value
    traded_b = candidate.traded_value_idr / 1_000_000_000
    if traded_b >= 1:
        traded_str = f"{traded_b:.1f}B IDR"
    else:
        traded_m = candidate.traded_value_idr / 1_000_000
        traded_str = f"{traded_m:.0f}M IDR"

    message = (
        f"🚀 *BPJS ALERT*\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"Ticker: *{ticker_clean}*\n"
        f"Score: *{candidate.score}*\n"
        f"Price: *{price_str} IDR*\n"
        f"Move: *{change_str}*\n"
        f"Vol: *{rvol_str}*\n"
        f"Value: *{traded_str}*\n"
        f"\n"
        f"*Signals:*\n"
        f"{signal_lines}\n"
        f"\n"
        f"*Potential:*\n"
        f"Intraday continuation setup\n"
        f"━━━━━━━━━━━━━━━━━━"
    )
    return message


def format_bsjp_alert(candidate: StockCandidate) -> str:
    """
    Formats a single BSJP candidate into a Telegram alert message.

    Args:
        candidate: StockCandidate with BSJP signals

    Returns:
        str: Formatted message text (Markdown compatible)
    """
    ticker_clean = candidate.ticker.replace(".JK", "")

    # Build signals section
    signal_lines = "\n".join(
        f"✅ {signal}" for signal in candidate.signals_triggered
    ) if candidate.signals_triggered else "⚠️ No strong signals"

    price_str = f"{candidate.price:,.0f}"

    change_sign = "+" if candidate.price_change_pct >= 0 else ""
    change_str = f"{change_sign}{candidate.price_change_pct:.1f}%"

    traded_b = candidate.traded_value_idr / 1_000_000_000
    if traded_b >= 1:
        traded_str = f"{traded_b:.1f}B IDR"
    else:
        traded_m = candidate.traded_value_idr / 1_000_000
        traded_str = f"{traded_m:.0f}M IDR"

    message = (
        f"🌙 *BSJP ALERT*\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"Ticker: *{ticker_clean}*\n"
        f"Score: *{candidate.score}*\n"
        f"Price: *{price_str} IDR*\n"
        f"Move: *{change_str}*\n"
        f"Value: *{traded_str}*\n"
        f"\n"
        f"*Signals:*\n"
        f"{signal_lines}\n"
        f"\n"
        f"*Potential:*\n"
        f"Overnight continuation setup\n"
        f"━━━━━━━━━━━━━━━━━━"
    )
    return message


def format_alert(candidate: StockCandidate) -> str:
    """
    Auto-selects the correct formatter based on candidate mode.

    Args:
        candidate: StockCandidate

    Returns:
        str: Formatted alert message
    """
    if candidate.mode == "BPJS":
        return format_bpjs_alert(candidate)
    return format_bsjp_alert(candidate)


def format_top_list(candidates: List[StockCandidate], mode: str) -> str:
    """
    Formats a ranked list of candidates for the /top command.

    Args:
        candidates: List of ranked StockCandidate objects
        mode: 'BPJS' or 'BSJP'

    Returns:
        str: Formatted summary message
    """
    if not candidates:
        return format_no_results(mode)

    emoji = "🚀" if mode == "BPJS" else "🌙"
    title = f"{emoji} *Top {mode} Candidates*\n━━━━━━━━━━━━━━━━━━\n"

    lines = []
    for i, c in enumerate(candidates, 1):
        ticker_clean = c.ticker.replace(".JK", "")
        change_sign = "+" if c.price_change_pct >= 0 else ""
        change_str = f"{change_sign}{c.price_change_pct:.1f}%"
        lines.append(
            f"{i}. *{ticker_clean}* — Score: {c.score} | "
            f"Price: {c.price:,.0f} | {change_str} | Vol: {c.rel_volume:.1f}x"
        )

    footer = "\n━━━━━━━━━━━━━━━━━━\n⚠️ _Not financial advice. DYOR._"
    return title + "\n".join(lines) + footer


def format_no_results(mode: str) -> str:
    """Returns message when no candidates found."""
    return (
        f"📭 *No {mode} candidates found*\n\n"
        f"Market conditions don't show qualifying setups right now.\n"
        f"Try again during active trading hours."
    )


def format_scan_header(mode: str) -> str:
    """Returns a scanning-in-progress message."""
    emoji = "🔍" if mode == "BPJS" else "🔍"
    return f"{emoji} *Running {mode} scan...*\nThis may take 1-2 minutes. Please wait."


def format_error(context: str) -> str:
    """Returns a generic error message."""
    return (
        f"⚠️ *Error during scan*\n\n"
        f"{context}\n\n"
        f"Please try again in a few minutes."
    )


def format_disclaimer() -> str:
    """Returns the standard disclaimer footer."""
    return "\n\n⚠️ _Not financial advice. Always DYOR. Trade at your own risk._"

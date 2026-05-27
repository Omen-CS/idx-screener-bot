"""
bot/utils/formatter.py
Format alert Telegram — dengan ARA potential indicator.
"""

from typing import List, TYPE_CHECKING

if TYPE_CHECKING:
    from screener.scanner import StockCandidate


def format_bpjs_alert(candidate) -> str:
    ticker_clean = candidate.ticker.replace(".JK", "")

    # Tambah label ARA jika terdeteksi
    ara_label = ""
    if candidate.ara_potential:
        ara_label = f"\n🔥 *ARA POTENTIAL* (score: {candidate.ara_score})"

    signal_lines = "\n".join(
        f"✅ {s}" for s in candidate.signals_triggered
    ) if candidate.signals_triggered else "⚠️ No strong signals"

    price_str   = f"{candidate.price:,.0f}"
    rvol_str    = f"{candidate.rel_volume:.1f}x"
    change_sign = "+" if candidate.price_change_pct >= 0 else ""
    change_str  = f"{change_sign}{candidate.price_change_pct:.1f}%"

    traded_b = candidate.traded_value_idr / 1_000_000_000
    if traded_b >= 1:
        traded_str = f"{traded_b:.1f}B IDR"
    else:
        traded_str = f"{candidate.traded_value_idr/1_000_000:.0f}M IDR"

    return (
        f"🚀 *BPJS ALERT*{ara_label}\n"
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
        f"{'🔥 Kandidat ARA besok' if candidate.ara_potential else 'Intraday continuation setup'}\n"
        f"━━━━━━━━━━━━━━━━━━"
    )


def format_bsjp_alert(candidate) -> str:
    ticker_clean = candidate.ticker.replace(".JK", "")

    ara_label = ""
    if candidate.ara_potential:
        ara_label = f"\n🔥 *ARA POTENTIAL* (score: {candidate.ara_score})"

    signal_lines = "\n".join(
        f"✅ {s}" for s in candidate.signals_triggered
    ) if candidate.signals_triggered else "⚠️ No strong signals"

    price_str  = f"{candidate.price:,.0f}"
    change_sign = "+" if candidate.price_change_pct >= 0 else ""
    change_str  = f"{change_sign}{candidate.price_change_pct:.1f}%"

    traded_b = candidate.traded_value_idr / 1_000_000_000
    if traded_b >= 1:
        traded_str = f"{traded_b:.1f}B IDR"
    else:
        traded_str = f"{candidate.traded_value_idr/1_000_000:.0f}M IDR"

    return (
        f"🌙 *BSJP ALERT*{ara_label}\n"
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
        f"{'🔥 Kandidat ARA besok' if candidate.ara_potential else 'Overnight continuation setup'}\n"
        f"━━━━━━━━━━━━━━━━━━"
    )


def format_alert(candidate) -> str:
    if candidate.mode == "BPJS":
        return format_bpjs_alert(candidate)
    return format_bsjp_alert(candidate)


def format_top_list(candidates: List, mode: str) -> str:
    if not candidates:
        return format_no_results(mode)

    emoji = "🚀" if mode == "BPJS" else "🌙"
    title = f"{emoji} *Top {mode} Candidates*\n━━━━━━━━━━━━━━━━━━\n"

    lines = []
    for i, c in enumerate(candidates, 1):
        ticker_clean = c.ticker.replace(".JK", "")
        change_sign  = "+" if c.price_change_pct >= 0 else ""
        change_str   = f"{change_sign}{c.price_change_pct:.1f}%"
        ara_tag      = " 🔥ARA" if c.ara_potential else ""
        lines.append(
            f"{i}. *{ticker_clean}*{ara_tag} — Score: {c.score} | "
            f"{c.price:,.0f} | {change_str} | Vol: {c.rel_volume:.1f}x"
        )

    footer = "\n━━━━━━━━━━━━━━━━━━\n⚠️ _Not financial advice. DYOR._"
    return title + "\n".join(lines) + footer


def format_no_results(mode: str) -> str:
    return (
        f"📭 *No {mode} candidates found*\n\n"
        f"Market conditions tidak menunjukkan setup yang valid saat ini."
    )


def format_scan_header(mode: str) -> str:
    return f"🔍 *Running {mode} scan...*\nMohon tunggu 1-2 menit."


def format_error(context: str) -> str:
    return f"⚠️ *Error*\n\n{context}\n\nCoba lagi dalam beberapa menit."


def format_disclaimer() -> str:
    return "\n⚠️ _Not financial advice. Always DYOR. Trade at your own risk._"


def format_scan_summary(
    bpjs_candidates: list,
    bsjp_candidates: list,
    total_scanned: int = 0,
) -> str:
    """
    Ringkasan akhir setelah semua alert dikirim.
    Tampilkan statistik dan highlight terbaik.
    """
    all_candidates = bpjs_candidates + bsjp_candidates
    if not all_candidates:
        return ""

    total_candidates = len(all_candidates)
    ara_candidates   = [c for c in all_candidates if c.ara_potential]
    bpjs_count       = len(bpjs_candidates)
    bsjp_count       = len(bsjp_candidates)

    # Stats
    scanned_str = f"{total_scanned} ticker" if total_scanned > 0 else "semua ticker"

    # Top by score
    top_score = max(all_candidates, key=lambda x: x.score)

    # Highest traded value
    top_value = max(all_candidates, key=lambda x: x.traded_value_idr)

    # Highest % move
    top_move  = max(all_candidates, key=lambda x: x.price_change_pct)

    lines = [
        "📊 *RINGKASAN SCAN*",
        "━━━━━━━━━━━━━━━━━━",
        f"🔍 Dipindai: *{scanned_str}*",
        f"📈 Masuk radar: *{total_candidates} saham* "
        f"(BPJS: {bpjs_count} | BSJP: {bsjp_count})",
    ]

    if ara_candidates:
        ara_names = ", ".join(c.ticker.replace(".JK","") for c in ara_candidates)
        lines.append(f"🔥 ARA Potential: *{len(ara_candidates)} saham* → {ara_names}")

    lines.append("")
    lines.append("*Top picks:*")

    # Gabung semua candidates, deduplicate by ticker, ambil score tertinggi
    seen = {}
    for c in all_candidates:
        if c.ticker not in seen or c.score > seen[c.ticker].score:
            seen[c.ticker] = c
    unique = sorted(seen.values(), key=lambda x: (x.ara_potential, x.score), reverse=True)

    for i, c in enumerate(unique[:5], 1):
        ticker_clean = c.ticker.replace(".JK", "")
        change_sign  = "+" if c.price_change_pct >= 0 else ""
        ara_tag      = " 🔥" if c.ara_potential else ""
        lines.append(
            f"{i}. *{ticker_clean}*{ara_tag} — Score {c.score} | "
            f"{change_sign}{c.price_change_pct:.1f}% | Vol {c.rel_volume:.1f}x"
        )

    lines.append("")

    # Highlights
    lines.append(f"⚡ *Strongest:* {top_score.ticker.replace('.JK','')} (score {top_score.score})")

    val_b = top_value.traded_value_idr / 1_000_000_000
    val_str = f"{val_b:.1f}B" if val_b >= 1 else f"{top_value.traded_value_idr/1_000_000:.0f}M"
    lines.append(f"💎 *Biggest value:* {top_value.ticker.replace('.JK','')} ({val_str} IDR)")
    lines.append(f"🚀 *Top mover:* {top_move.ticker.replace('.JK','')} (+{top_move.price_change_pct:.1f}%)")

    if ara_candidates:
        ara_watch = " | ".join(c.ticker.replace(".JK","") for c in ara_candidates)
        lines.append(f"🔥 *ARA watch:* {ara_watch}")

    lines.append("━━━━━━━━━━━━━━━━━━")
    lines.append("⚠️ _Not financial advice. DYOR._")

    return "\n".join(lines)

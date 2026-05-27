"""
bot/utils/formatter.py — dengan continuation label
"""
from typing import List


def _continuation_badge(label: str) -> str:
    if label == "HIGH CONTINUATION":
        return "🔥 *HIGH CONTINUATION*"
    elif label == "POSSIBLE EXHAUSTION":
        return "⚠️ *POSSIBLE EXHAUSTION*"
    elif label == "ONE DAY SPIKE":
        return "💤 *ONE DAY SPIKE*"
    return ""


def format_bpjs_alert(candidate) -> str:
    ticker_clean = candidate.ticker.replace(".JK", "")

    badges = []
    if candidate.ara_potential:
        badges.append(f"🎯 *ARA POTENTIAL* (score: {candidate.ara_score})")
    cont = _continuation_badge(getattr(candidate, 'continuation_label', ''))
    if cont:
        badges.append(cont)
    badge_str = "\n".join(badges)
    if badge_str:
        badge_str = "\n" + badge_str

    signal_lines = "\n".join(f"✅ {s}" for s in candidate.signals_triggered) \
        if candidate.signals_triggered else "⚠️ No strong signals"

    price_str   = f"{candidate.price:,.0f}"
    rvol_str    = f"{candidate.rel_volume:.1f}x"
    change_sign = "+" if candidate.price_change_pct >= 0 else ""
    change_str  = f"{change_sign}{candidate.price_change_pct:.1f}%"
    traded_b    = candidate.traded_value_idr / 1_000_000_000
    traded_str  = f"{traded_b:.1f}B IDR" if traded_b >= 1 else f"{candidate.traded_value_idr/1_000_000:.0f}M IDR"

    potential_str = "🔥 Kandidat ARA besok" if candidate.ara_potential else "Intraday continuation setup"

    return (
        f"🚀 *BPJS ALERT*{badge_str}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"Ticker: *{ticker_clean}*\n"
        f"Score: *{candidate.score}*\n"
        f"Price: *{price_str} IDR*\n"
        f"Move: *{change_str}*\n"
        f"Vol: *{rvol_str}*\n"
        f"Value: *{traded_str}*\n"
        f"\n*Signals:*\n{signal_lines}\n"
        f"\n*Potential:*\n{potential_str}\n"
        f"━━━━━━━━━━━━━━━━━━"
    )


def format_bsjp_alert(candidate) -> str:
    ticker_clean = candidate.ticker.replace(".JK", "")

    badges = []
    if candidate.ara_potential:
        badges.append(f"🎯 *ARA POTENTIAL* (score: {candidate.ara_score})")
    cont = _continuation_badge(getattr(candidate, 'continuation_label', ''))
    if cont:
        badges.append(cont)
    badge_str = "\n".join(badges)
    if badge_str:
        badge_str = "\n" + badge_str

    signal_lines = "\n".join(f"✅ {s}" for s in candidate.signals_triggered) \
        if candidate.signals_triggered else "⚠️ No strong signals"

    price_str  = f"{candidate.price:,.0f}"
    change_sign = "+" if candidate.price_change_pct >= 0 else ""
    change_str  = f"{change_sign}{candidate.price_change_pct:.1f}%"
    traded_b   = candidate.traded_value_idr / 1_000_000_000
    traded_str = f"{traded_b:.1f}B IDR" if traded_b >= 1 else f"{candidate.traded_value_idr/1_000_000:.0f}M IDR"

    potential_str = "🔥 Kandidat ARA besok" if candidate.ara_potential else "Overnight continuation setup"

    return (
        f"🌙 *BSJP ALERT*{badge_str}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"Ticker: *{ticker_clean}*\n"
        f"Score: *{candidate.score}*\n"
        f"Price: *{price_str} IDR*\n"
        f"Move: *{change_str}*\n"
        f"Value: *{traded_str}*\n"
        f"\n*Signals:*\n{signal_lines}\n"
        f"\n*Potential:*\n{potential_str}\n"
        f"━━━━━━━━━━━━━━━━━━"
    )


def format_alert(candidate) -> str:
    return format_bpjs_alert(candidate) if candidate.mode == "BPJS" else format_bsjp_alert(candidate)


def format_top_list(candidates: List, mode: str) -> str:
    if not candidates:
        return format_no_results(mode)

    emoji = "🚀" if mode == "BPJS" else "🌙"
    lines = [f"{emoji} *Top {mode} Candidates*\n━━━━━━━━━━━━━━━━━━"]

    for i, c in enumerate(candidates, 1):
        ticker_clean = c.ticker.replace(".JK", "")
        change_sign  = "+" if c.price_change_pct >= 0 else ""
        change_str   = f"{change_sign}{c.price_change_pct:.1f}%"
        tags = ""
        if c.ara_potential:
            tags += " 🎯ARA"
        cont = getattr(c, 'continuation_label', '')
        if cont == "HIGH CONTINUATION":
            tags += " 🔥"
        elif cont == "POSSIBLE EXHAUSTION":
            tags += " ⚠️"
        elif cont == "ONE DAY SPIKE":
            tags += " 💤"
        lines.append(
            f"{i}. *{ticker_clean}*{tags} — {c.score} | "
            f"{c.price:,.0f} | {change_str} | {c.rel_volume:.1f}x"
        )

    lines.append("\n━━━━━━━━━━━━━━━━━━\n⚠️ _Not financial advice. DYOR._")
    return "\n".join(lines)


def format_scan_summary(bpjs_candidates: list, bsjp_candidates: list,
                        total_scanned: int = 0) -> str:
    all_c = bpjs_candidates + bsjp_candidates
    if not all_c:
        return ""

    ara_list  = [c for c in all_c if c.ara_potential]
    high_list = [c for c in all_c if getattr(c, 'continuation_label', '') == "HIGH CONTINUATION"]
    exhaust   = [c for c in all_c if getattr(c, 'continuation_label', '') == "POSSIBLE EXHAUSTION"]
    spike     = [c for c in all_c if getattr(c, 'continuation_label', '') == "ONE DAY SPIKE"]

    scanned_str = f"{total_scanned} ticker" if total_scanned > 0 else "semua ticker"

    lines = [
        "📊 *RINGKASAN SCAN*",
        "━━━━━━━━━━━━━━━━━━",
        f"🔍 Dipindai: *{scanned_str}*",
        f"📈 Masuk radar: *{len(all_c)} saham* (BPJS: {len(bpjs_candidates)} | BSJP: {len(bsjp_candidates)})",
    ]

    if high_list:
        names = " | ".join(c.ticker.replace(".JK","") for c in high_list[:5])
        lines.append(f"🔥 High Continuation: *{len(high_list)}* → {names}")
    if ara_list:
        names = " | ".join(c.ticker.replace(".JK","") for c in ara_list[:5])
        lines.append(f"🎯 ARA Potential: *{len(ara_list)}* → {names}")
    if exhaust:
        names = " | ".join(c.ticker.replace(".JK","") for c in exhaust[:3])
        lines.append(f"⚠️ Possible Exhaustion: *{len(exhaust)}* → {names}")
    if spike:
        names = " | ".join(c.ticker.replace(".JK","") for c in spike[:3])
        lines.append(f"💤 One Day Spike: *{len(spike)}* → {names}")

    # Dedup by ticker
    seen = {}
    for c in all_c:
        if c.ticker not in seen or c.score > seen[c.ticker].score:
            seen[c.ticker] = c

    def sort_key(c):
        cont = getattr(c, 'continuation_label', '')
        p = {"HIGH CONTINUATION": 3, "": 2, "POSSIBLE EXHAUSTION": 1, "ONE DAY SPIKE": 0}
        return (c.ara_potential, p.get(cont, 0), c.score)

    unique = sorted(seen.values(), key=sort_key, reverse=True)

    lines.append("\n*Top picks:*")
    for i, c in enumerate(unique[:5], 1):
        t = c.ticker.replace(".JK","")
        sign = "+" if c.price_change_pct >= 0 else ""
        tag = ""
        if c.ara_potential: tag += "🎯"
        cont = getattr(c, 'continuation_label', '')
        if cont == "HIGH CONTINUATION": tag += "🔥"
        elif cont == "POSSIBLE EXHAUSTION": tag += "⚠️"
        elif cont == "ONE DAY SPIKE": tag += "💤"
        lines.append(f"{i}. *{t}* {tag} Score {c.score} | {sign}{c.price_change_pct:.1f}% | Vol {c.rel_volume:.1f}x")

    top_score = max(all_c, key=lambda x: x.score)
    top_value = max(all_c, key=lambda x: x.traded_value_idr)
    top_move  = max(all_c, key=lambda x: x.price_change_pct)

    lines.append("")
    lines.append(f"⚡ *Strongest:* {top_score.ticker.replace('.JK','')} (score {top_score.score})")
    val_b = top_value.traded_value_idr / 1_000_000_000
    val_s = f"{val_b:.1f}B" if val_b >= 1 else f"{top_value.traded_value_idr/1_000_000:.0f}M"
    lines.append(f"💎 *Biggest value:* {top_value.ticker.replace('.JK','')} ({val_s} IDR)")
    lines.append(f"🚀 *Top mover:* {top_move.ticker.replace('.JK','')} (+{top_move.price_change_pct:.1f}%)")

    lines.append("━━━━━━━━━━━━━━━━━━")
    lines.append("⚠️ _Not financial advice. DYOR._")
    return "\n".join(lines)


def format_no_results(mode: str) -> str:
    return f"📭 *No {mode} candidates found*\n\nTidak ada setup yang valid saat ini."


def format_scan_header(mode: str) -> str:
    return f"🔍 *Running {mode} scan...*\nMohon tunggu 1-3 menit."


def format_error(context: str) -> str:
    return f"⚠️ *Error*\n\n{context}\n\nCoba lagi dalam beberapa menit."


def format_disclaimer() -> str:
    return "\n⚠️ _Not financial advice. Always DYOR. Trade at your own risk._"

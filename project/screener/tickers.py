"""
screener/tickers.py — 50 ticker paling liquid IDX

Dikurangi ke 50 supaya:
- Total fetch time ~2 menit (bisa ditoleransi user)
- Tidak kena rate limit 429 Yahoo Finance
- Fokus ke saham yang benar-benar liquid dan aktif
"""

import logging
from typing import List

logger = logging.getLogger(__name__)

CURATED_IDX_TICKERS: List[str] = [
    # LQ45 Blue Chips (20)
    "BBCA.JK", "BBRI.JK", "BMRI.JK", "BBNI.JK", "BRIS.JK",
    "TLKM.JK", "ASII.JK", "UNVR.JK", "ICBP.JK", "INDF.JK",
    "ANTM.JK", "PTBA.JK", "ADRO.JK", "PGAS.JK", "MDKA.JK",
    "BUMI.JK", "INCO.JK", "TINS.JK", "CPIN.JK", "MYOR.JK",

    # MidCap Aktif (15)
    "GOTO.JK", "BUKA.JK", "ARTO.JK", "MTEL.JK", "DCII.JK",
    "HEAL.JK", "MIKA.JK", "TBIG.JK", "TOWR.JK", "SCMA.JK",
    "CTRA.JK", "PWON.JK", "SMRA.JK", "BSDE.JK", "JSMR.JK",

    # Spekulatif Populer (15)
    "DEWA.JK", "MBMA.JK", "NCKL.JK", "BRMS.JK", "CUAN.JK",
    "BHAT.JK", "WIFI.JK", "INET.JK", "HRUM.JK", "BYAN.JK",
    "GEMS.JK", "FIRE.JK", "TPMA.JK", "STRK.JK", "NFCX.JK",
]


def get_idx_tickers() -> List[str]:
    tickers = list(dict.fromkeys(CURATED_IDX_TICKERS))
    logger.info(f"Total tickers to scan: {len(tickers)}")
    return tickers


def get_ticker_base(ticker: str) -> str:
    return ticker.replace(".JK", "")

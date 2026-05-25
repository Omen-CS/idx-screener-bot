"""
screener/tickers.py
Daftar ticker IDX yang liquid dan aktif diperdagangkan.

Dikurangi dari 218 → 80 ticker paling liquid.
Alasan: Yahoo Finance rate limit 429 kalau terlalu banyak request sekaligus.
80 ticker dengan bulk download = ~4 request total, jauh lebih aman.
"""

import logging
from typing import List

logger = logging.getLogger(__name__)

# 80 ticker IDX paling liquid: LQ45 + MidCap aktif + spekulatif populer
CURATED_IDX_TICKERS: List[str] = [
    # LQ45 Blue Chips
    "BBCA.JK", "BBRI.JK", "BMRI.JK", "BBNI.JK", "BRIS.JK",
    "TLKM.JK", "ASII.JK", "UNVR.JK", "ICBP.JK", "INDF.JK",
    "KLBF.JK", "SMGR.JK", "ANTM.JK", "PTBA.JK", "ADRO.JK",
    "ITMG.JK", "PGAS.JK", "AKRA.JK", "EXCL.JK", "ISAT.JK",
    "MNCN.JK", "MDKA.JK", "BUMI.JK", "INCO.JK", "TINS.JK",
    "WIKA.JK", "PTPP.JK", "WSKT.JK", "JSMR.JK", "BSDE.JK",
    "CTRA.JK", "PWON.JK", "SMRA.JK", "GGRM.JK", "HMSP.JK",
    "MYOR.JK", "CPIN.JK", "TOWR.JK", "SCMA.JK", "EMTK.JK",

    # MidCap Momentum
    "ACES.JK", "MAPI.JK", "AMRT.JK", "HEAL.JK", "MIKA.JK",
    "ULTJ.JK", "TBIG.JK", "BNGA.JK", "BJBR.JK", "BDMN.JK",
    "BTPS.JK", "AALI.JK", "LSIP.JK", "SGRO.JK", "SSIA.JK",
    "ASRI.JK", "BEST.JK", "DILD.JK", "KAEF.JK", "TSPC.JK",

    # Spekulatif & Retail Favorit
    "GOTO.JK", "BUKA.JK", "ARTO.JK", "MTEL.JK", "DCII.JK",
    "DEWA.JK", "MBMA.JK", "NCKL.JK", "BRMS.JK", "CUAN.JK",
    "BHAT.JK", "WIFI.JK", "INET.JK", "STRK.JK", "NFCX.JK",
    "TPMA.JK", "FIRE.JK", "GEMS.JK", "BYAN.JK", "HRUM.JK",

    # Banking & Finance Tambahan
    "PNBN.JK", "MEGA.JK", "BJTM.JK", "NISP.JK", "NOBU.JK",
]


def get_idx_tickers() -> List[str]:
    """Return daftar ticker IDX yang akan di-scan."""
    tickers = list(dict.fromkeys(CURATED_IDX_TICKERS))  # deduplicate, keep order
    logger.info(f"Total tickers to scan: {len(tickers)}")
    return tickers


def get_ticker_base(ticker: str) -> str:
    return ticker.replace(".JK", "")

"""
screener/tickers.py
Dynamically fetches and manages Indonesian IDX stock tickers.

Strategy:
- Primary: use a curated list of liquid IDX stocks (LQ45 + MidCap + popular speculative)
- Extended: attempt to fetch from IDX/public sources
- Fallback: use built-in curated list

All tickers use the .JK suffix required by yfinance for IDX stocks.
"""

import logging
import requests
import time
from typing import List

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Curated IDX ticker list
# Covers: LQ45 blue chips + MidCap momentum + popular speculative stocks
# This list is updated periodically — it covers ~200 active IDX stocks
# ---------------------------------------------------------------------------
CURATED_IDX_TICKERS: List[str] = [
    # LQ45 Blue Chips
    "BBCA.JK", "BBRI.JK", "BMRI.JK", "BBNI.JK", "BRIS.JK",
    "TLKM.JK", "ASII.JK", "UNVR.JK", "ICBP.JK", "INDF.JK",
    "KLBF.JK", "SIDO.JK", "SMGR.JK", "INTP.JK", "SMBR.JK",
    "ANTM.JK", "PTBA.JK", "ADRO.JK", "ITMG.JK", "HRUM.JK",
    "PGAS.JK", "AKRA.JK", "EXCL.JK", "ISAT.JK", "TOWR.JK",
    "MNCN.JK", "SCMA.JK", "EMTK.JK", "MDKA.JK", "BUMI.JK",
    "INCO.JK", "TINS.JK", "DOID.JK", "PSAB.JK", "ELSA.JK",
    "WIKA.JK", "PTPP.JK", "WSKT.JK", "ADHI.JK", "JSMR.JK",
    "BSDE.JK", "CTRA.JK", "PWON.JK", "SMRA.JK", "LPKR.JK",
    "GGRM.JK", "HMSP.JK", "WIIM.JK", "MYOR.JK", "CPIN.JK",

    # MidCap Momentum Stocks
    "ACES.JK", "MAPI.JK", "LPPF.JK", "RALS.JK", "HERO.JK",
    "AMRT.JK", "DMAS.JK", "SILO.JK", "HEAL.JK", "MIKA.JK",
    "KINO.JK", "ULTJ.JK", "DLTA.JK", "SKBM.JK", "AISA.JK",
    "FAST.JK", "TBIG.JK", "LINK.JK", "CENT.JK", "FREN.JK",
    "BNGA.JK", "BJBR.JK", "BDMN.JK", "NISP.JK", "PNBN.JK",
    "MEGA.JK", "BTPS.JK", "BJTM.JK", "BANK.JK", "AGRO.JK",
    "TAPG.JK", "AALI.JK", "LSIP.JK", "SGRO.JK", "TBLA.JK",
    "PALM.JK", "DSNG.JK", "SSMS.JK", "BWPT.JK", "JAWA.JK",
    "SSIA.JK", "DILD.JK", "ASRI.JK", "BEST.JK", "MTLA.JK",
    "APLN.JK", "GPRA.JK", "PJAA.JK", "MPRO.JK", "NZIA.JK",

    # Speculative & Retail Favorites
    "BBKP.JK", "BABP.JK", "AGRS.JK", "BBYB.JK", "NOBU.JK",
    "TRIM.JK", "YULE.JK", "MRAT.JK", "KICI.JK", "TELE.JK",
    "BHAT.JK", "SKYB.JK", "TRST.JK", "AKKU.JK", "BEKS.JK",
    "MSIN.JK", "WIFI.JK", "DCII.JK", "EDGE.JK", "MTEL.JK",
    "GOTO.JK", "BUKA.JK", "ARTO.JK", "STRK.JK", "NFCX.JK",
    "DEWA.JK", "MBMA.JK", "NICL.JK", "NCKL.JK", "TPMA.JK",
    "BRMS.JK", "CUAN.JK", "INET.JK", "SONA.JK", "SMKL.JK",
    "GULA.JK", "KRYA.JK", "JGLE.JK", "ESTA.JK", "CBMF.JK",
    "MABA.JK", "RISE.JK", "PPGL.JK", "CITY.JK", "PURI.JK",
    "RANC.JK", "KIOS.JK", "HOPE.JK", "FOOD.JK", "HAJJ.JK",

    # Mining & Commodities
    "DKFT.JK", "ARII.JK", "BYAN.JK", "PKPK.JK", "GEMS.JK",
    "FIRE.JK", "SMMT.JK", "GTBO.JK", "MYOH.JK", "BORN.JK",
    "ZINC.JK", "CNKO.JK", "ENRG.JK", "RUIS.JK", "MBAP.JK",
    "TOBA.JK", "GTSI.JK", "ABMM.JK", "HELI.JK", "MCAS.JK",

    # Infrastructure & Utilities
    "BIRD.JK", "MPMX.JK", "TAXI.JK", "LRNA.JK", "WEHA.JK",
    "SOCI.JK", "WINS.JK", "TMAS.JK", "IPCC.JK", "NELY.JK",
    "BULL.JK", "BLTA.JK", "SMDR.JK", "TPMA.JK", "MBSS.JK",
    "PGAS.JK", "MEDC.JK", "RIGS.JK", "BIPI.JK", "ESSA.JK",

    # Healthcare & Pharma
    "KAEF.JK", "PYFA.JK", "TSPC.JK", "MERK.JK", "INAF.JK",
    "PRDA.JK", "SHID.JK", "SAME.JK", "BMHS.JK", "PRIM.JK",

    # Consumer & Retail
    "MPPA.JK", "CSAP.JK", "MIDI.JK", "SPAR.JK", "TGKA.JK",
    "SDPC.JK", "EPMT.JK", "WAPO.JK", "KOIN.JK", "MPIX.JK",

    # Technology
    "MLPT.JK", "DMMX.JK", "DNET.JK", "TECH.JK", "ATIC.JK",
    "MTDL.JK", "LUCK.JK", "SWAT.JK", "HAIS.JK", "TFAS.JK",
]


def get_idx_tickers() -> List[str]:
    """
    Returns a deduplicated list of IDX tickers to scan.

    Tries to extend the curated list with dynamically fetched tickers,
    falls back to curated list only on any error.

    Returns:
        List[str]: List of ticker symbols ending in .JK
    """
    tickers = set(CURATED_IDX_TICKERS)

    # Attempt to fetch additional tickers from public IDX data
    try:
        additional = _fetch_idx_tickers_from_web()
        tickers.update(additional)
        logger.info(f"Extended ticker list to {len(tickers)} tickers")
    except Exception as e:
        logger.warning(f"Could not fetch additional tickers: {e}. Using curated list only.")

    result = sorted(list(tickers))
    logger.info(f"Total tickers to scan: {len(result)}")
    return result


def _fetch_idx_tickers_from_web() -> List[str]:
    """
    Attempts to fetch IDX tickers from a public source.
    Uses the IDX sector data available via Yahoo Finance screening.

    Returns:
        List[str]: Additional tickers found, may be empty.
    """
    additional: List[str] = []

    # Try fetching from IDX official sector listing via a public API
    # This uses the screener endpoint that lists Indonesian stocks
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (compatible; IDX-Screener-Bot/1.0)"
        }
        # Yahoo Finance screener for Indonesian market
        url = (
            "https://query2.finance.yahoo.com/v1/finance/screener"
            "?formatted=false&lang=en-US&region=ID"
            "&count=200&offset=0"
        )
        params = {
            "crumb": "",  # public endpoint doesn't need crumb for basic queries
        }
        # Simple GET to Yahoo Finance for ID region stocks
        resp = requests.get(
            "https://query1.finance.yahoo.com/v1/finance/screener/predefined/saved"
            "?formatted=false&lang=en-US&region=ID&scrIds=ms_id&count=200",
            headers=headers,
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json()
            quotes = data.get("finance", {}).get("result", [{}])[0].get("quotes", [])
            for q in quotes:
                sym = q.get("symbol", "")
                if sym.endswith(".JK") and sym not in CURATED_IDX_TICKERS:
                    additional.append(sym)
    except Exception:
        pass  # Silently fall back — curated list is sufficient

    return additional


def get_ticker_base(ticker: str) -> str:
    """
    Returns the base ticker without the .JK suffix.

    Args:
        ticker: Full ticker like 'ANTM.JK'

    Returns:
        str: Base ticker like 'ANTM'
    """
    return ticker.replace(".JK", "")

"""
Wspólny helper deduplikacji ofert OLX.

OLX zmienia slug w URL gdy sprzedawca edytuje tytuł ogłoszenia.
Stabilnym identyfikatorem jest fragment `CID3-IDxxxx` w URL/slugu.

Wcześniej `extract_cid` był zduplikowany w main.py i scraper.py — teraz
jest jedno źródło prawdy. Importuj stąd: `from cid import extract_cid`.
"""

import re

_CID_RE = re.compile(r'(CID3-ID[A-Za-z0-9]+)')


def extract_cid(s: str) -> str:
    """Wyciąga stabilny identyfikator CID3-IDxxxx z URL lub slugu.

    Fallback: zwraca cały string (lub '' dla None), gdy brak CID.
    """
    m = _CID_RE.search(s or '')
    return m.group(1) if m else (s or '')

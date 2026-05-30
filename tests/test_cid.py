"""Testy stabilnego identyfikatora oferty (CID3-IDxxxx).

Po refaktorze 2026-05-30 extract_cid jest w jednym module (cid.py) i
współdzielony przez main.py oraz scraper.py.
"""

import pytest

from cid import extract_cid


@pytest.mark.parametrize("inp,expected", [
    ("foo-bar-CID3-IDabc123.html", "CID3-IDabc123"),
    ("https://www.olx.pl/d/oferta/mieszkanie-CID3-ID14gaar", "CID3-ID14gaar"),
    ("zmieniony-tytul-CID3-ID14gaar.html", "CID3-ID14gaar"),
    ("nocid-here", "nocid-here"),   # fallback: cały string
    ("", ""),                        # pusty
    (None, ""),                      # None → ''
])
def test_extract_cid(inp, expected):
    assert extract_cid(inp) == expected


def test_same_cid_for_edited_slug():
    """Edycja tytułu zmienia slug, ale CID musi pozostać stabilny."""
    a = "kawalerka-centrum-CID3-IDxyz9"
    b = "super-kawalerka-tanio-CID3-IDxyz9"
    assert extract_cid(a) == extract_cid(b) == "CID3-IDxyz9"


def test_shared_across_modules():
    """main, scraper i quick_scan muszą używać DOKŁADNIE tej samej funkcji."""
    import main
    import scraper
    import quick_scan
    assert main.extract_cid is scraper.extract_cid
    assert quick_scan.extract_cid is main.extract_cid

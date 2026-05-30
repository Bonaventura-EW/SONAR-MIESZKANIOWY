"""Testy parsera cen."""

import pytest

from price_parser import PriceParser


@pytest.fixture(scope="module")
def parser():
    return PriceParser()


@pytest.mark.parametrize("text,price,media", [
    ("Wynajem 850 zł wszystko wliczone", 850, "wliczone"),
    ("Pokój 700 zł + media ok. 150 zł", 700, "+ media"),
    ("Cena: 1100 zł – w tym wszystkie opłaty (850 zł – pokój + 250 zł – opłaty)",
     850, "+ 250 zł opłaty"),
])
def test_extracts_price(parser, text, price, media):
    result = parser.extract_price(text)
    assert result is not None, f"Nie wykryto ceny w: {text!r}"
    assert result["price"] == price
    assert result["media_info"] == media


def test_returns_none_without_pattern(parser):
    """Bez wzorca ceny parser zwraca None (nie zgaduje pierwszej liczby)."""
    assert parser.extract_price("Cena 600 bez mediów") is None


def test_detect_media_info_only(parser):
    assert parser.detect_media_info_only("wszystko wliczone w cenie czynszu") == "wliczone"
    assert parser.detect_media_info_only("czynsz + media osobno") == "+ media"

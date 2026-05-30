"""Testy ekstrakcji adresów (regresja na faktyczne, poprawne zachowanie)."""

import pytest

from address_parser import AddressParser


@pytest.fixture(scope="module")
def parser():
    # Whitelist znanych ulic z realnego cache (jeśli istnieje).
    return AddressParser(geocoding_cache_path="../data/geocoding_cache.json")


@pytest.mark.parametrize("text,expected_full", [
    ("Narutowicza 38, mieszkanie 4-pokojowe", "Narutowicza 38"),
    ("ul. Lipowa 10, blisko UMCS", "Lipowa 10"),
    ("al. Andersa 13", "Aleja Andersa 13"),
    ("Aleje Racławickie 12/2", "Aleje Racławickie 12/2"),
    # Słowo "mieszkaniowe" doklejone do ulicy ma zostać odcięte
    ("Bursztynowa Mieszkanie 65m", "Bursztynowa 65m"),
])
def test_extracts_address(parser, text, expected_full):
    result = parser.extract_address(text)
    assert result is not None, f"Nie wykryto adresu w: {text!r}"
    assert result["full"] == expected_full


@pytest.mark.parametrize("text", [
    "100 metrów od UMCS",      # "X metrów od" to nie adres
    "UMCS 10 minut pieszo",    # instytucja + "minut"
    "5 minut od centrum",
])
def test_rejects_non_address(parser, text):
    assert parser.extract_address(text) is None


def test_excluded_word_alone_is_rejected(parser):
    """Sama dzielnica/instytucja bez prawdziwej ulicy → None."""
    assert parser.extract_address("Centrum 5 minut") is None

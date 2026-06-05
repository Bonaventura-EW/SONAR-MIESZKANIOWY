"""Test regresyjny zawartości EXCLUDED_WORDS.

Po usunięciu zdublowanych wpisów (2026-05-30) zbiór MUSI pozostać identyczny
co do zawartości. Ten test pilnuje, że przyszłe porządki nie zgubią słowa.
"""

from address_parser import AddressParser

EXPECTED_COUNT = 249


def test_count():
    assert len(AddressParser.EXCLUDED_WORDS) == EXPECTED_COUNT


def test_all_lowercase():
    """Konwencja: wszystkie wpisy muszą być lowercase (porównanie po .lower())."""
    for w in AddressParser.EXCLUDED_WORDS:
        assert w == w.lower(), f"Wpis nie jest lowercase: {w!r}"


def test_critical_words_present():
    """Słowa-pułapki specyficzne dla mieszkań — krytyczne dla parsera."""
    must_have = {
        "mieszkanie", "kawalerka", "apartament", "studio",
        "kaucja", "klimatyzacja", "wysokość", "wnętrz",
        "umcs", "kul", "centrum", "lublin", "lsm",
        "przy", "blisko", "okolice",
    }
    missing = must_have - AddressParser.EXCLUDED_WORDS
    assert not missing, f"Brakuje krytycznych słów: {missing}"

"""Testy detektora duplikatów."""

import pytest

from duplicate_detector import DuplicateDetector


@pytest.fixture(scope="module")
def detector():
    return DuplicateDetector(similarity_threshold=0.95)


def test_identical_similarity(detector):
    assert detector.calculate_similarity("abc def", "abc def") == 1.0


def test_empty_similarity(detector):
    assert detector.calculate_similarity("", "cokolwiek") == 0.0


def test_duplicate_same_address_high_similarity(detector):
    o1 = {"address": {"full": "Narutowicza 5"},
          "description": "Pokój przy Narutowicza 5, 700 zł, umeblowany ladnie"}
    o2 = {"address": {"full": "Narutowicza 5"},
          "description": "Pokój przy Narutowicza 5, 700 zł, umeblowany ladnie!"}
    assert detector.is_duplicate(o1, o2) is True


def test_different_address_not_duplicate(detector):
    o1 = {"address": {"full": "Narutowicza 5"}, "description": "Pokój 700 zł"}
    o2 = {"address": {"full": "Lipowa 10"}, "description": "Pokój 700 zł"}
    assert detector.is_duplicate(o1, o2) is False


def test_same_address_low_similarity_not_duplicate(detector):
    o1 = {"address": {"full": "Narutowicza 5"},
          "description": "Słoneczna kawalerka z balkonem i nowym wyposażeniem"}
    o2 = {"address": {"full": "Narutowicza 5"},
          "description": "Ciemny pokój do remontu bez mebli, tani"}
    assert detector.is_duplicate(o1, o2) is False


def test_find_duplicate_returns_original(detector):
    new = {"address": {"full": "Lipowa 10"}, "description": "Mieszkanie dwupokojowe ladne"}
    existing = [{"address": {"full": "Lipowa 10"}, "description": "Mieszkanie dwupokojowe ladne!"}]
    assert detector.find_duplicate(new, existing) is existing[0]
    assert detector.find_duplicate(new, []) is None


def test_address_key_normalizes(detector):
    a = {"address": {"full": "  Lipowa 10  "}}
    b = {"address": {"full": "lipowa 10"}}
    assert detector.address_key(a) == detector.address_key(b) == "lipowa 10"


def test_indexed_matches_linear(detector):
    """find_duplicate_indexed musi dać identyczny wynik jak liniowy find_duplicate."""
    offers = [
        {"address": {"full": "Lipowa 10"}, "description": "Mieszkanie dwupokojowe ladne"},
        {"address": {"full": "Narutowicza 5"}, "description": "Kawalerka z balkonem"},
        {"address": {"full": "Lipowa 10"}, "description": "Zupelnie inny opis remont"},
    ]
    # Zbuduj indeks tak jak main.py
    index = {}
    for o in offers:
        index.setdefault(detector.address_key(o), []).append(o)

    cases = [
        {"address": {"full": "Lipowa 10"}, "description": "Mieszkanie dwupokojowe ladne!"},  # dup #0
        {"address": {"full": "Lipowa 10"}, "description": "Totalnie nowy tekst bez zwiazku"},  # brak
        {"address": {"full": "Kowalska 1"}, "description": "Cokolwiek"},  # inny adres
    ]
    for c in cases:
        assert detector.find_duplicate_indexed(c, index) is detector.find_duplicate(c, offers)


def test_indexed_empty_index(detector):
    assert detector.find_duplicate_indexed(
        {"address": {"full": "Lipowa 10"}, "description": "x"}, {}
    ) is None

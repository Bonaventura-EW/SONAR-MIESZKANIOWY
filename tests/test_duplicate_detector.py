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

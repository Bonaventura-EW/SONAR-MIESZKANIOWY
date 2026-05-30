"""Testy generatora mapy — split opisów na podgląd + lazy-load (punkt 6)."""

import map_generator
from map_generator import split_description, DESC_PREVIEW_LEN


def test_short_description_not_truncated():
    txt = "Krótki opis mieszkania"
    preview, truncated = split_description(txt)
    assert preview == txt
    assert truncated is False


def test_exact_boundary_not_truncated():
    txt = "x" * DESC_PREVIEW_LEN
    preview, truncated = split_description(txt)
    assert preview == txt
    assert truncated is False


def test_long_description_truncated():
    txt = "a" * (DESC_PREVIEW_LEN + 500)
    preview, truncated = split_description(txt)
    assert truncated is True
    assert preview.endswith("…")
    # Podgląd nie dłuższy niż limit + znak wielokropka
    assert len(preview) <= DESC_PREVIEW_LEN + 1


def test_empty_and_none():
    assert split_description("") == ("", False)
    assert split_description(None) == ("", False)

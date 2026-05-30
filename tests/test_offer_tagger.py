"""Testy tagowania ofert (kawalerka / pokój / mieszkanie)."""

import pytest

from offer_tagger import tag_offer, determine_tags


@pytest.mark.parametrize("title,desc,primary", [
    ("Kawalerka Śródmieście", "Studio 25m2 aneks", "kawalerka"),
    ("Mieszkanie 3-pokojowe", "Całe mieszkanie z trzema pokojami", "mieszkanie"),
    ("Pokój dla studentki", "Wolny pokój w mieszkaniu, blisko UMCS", "pokoj"),
])
def test_primary_tag(title, desc, primary):
    assert tag_offer(title, desc)["primary"] == primary


def test_result_structure():
    r = tag_offer("Mieszkanie", "Ladne mieszkanie do wynajęcia")
    assert set(r) >= {"primary", "secondary", "all_tags", "scores", "confidence"}
    assert 0.0 <= r["confidence"] <= 1.0


def test_empty_defaults_to_mieszkanie():
    """Brak sygnałów → domyślnie 'mieszkanie' (kategoria OLX)."""
    assert determine_tags({"pokoj": 0.0, "kawalerka": 0.0, "mieszkanie": 0.0})["primary"] == "mieszkanie"

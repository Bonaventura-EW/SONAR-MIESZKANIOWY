"""Testy tagowania ofert (kawalerka / pokój / mieszkanie)."""

import pytest

from offer_tagger import tag_offer, determine_tags, build_tags, title_from_url


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


def test_build_tags_shape():
    """build_tags zwraca kształt zapisywany w offers.json/data.json."""
    t = build_tags("Kawalerka", "Studio 25m2")
    assert set(t) == {"primary", "secondary", "all", "confidence"}
    assert t["primary"] == "kawalerka"
    assert isinstance(t["all"], list) and t["primary"] in t["all"]


def test_title_from_url():
    assert title_from_url("https://x/d/oferta/mieszkanie-3-pok-CID3-IDabc.html") == "mieszkanie 3 pok CID3 IDabc"
    assert title_from_url("") == ""


def test_resolve_tags_prefers_stored():
    """map_generator.resolve_tags czyta zapisane tagi, fallback liczy w locie."""
    from map_generator import resolve_tags
    stored = {"primary": "pokoj", "secondary": ["mieszkanie"], "all": ["pokoj", "mieszkanie"], "confidence": 0.9}
    offer_with = {"tags": stored, "url": "x", "description": "y"}
    assert resolve_tags(offer_with)["primary"] == "pokoj"

    offer_without = {"url": "https://x/d/oferta/kawalerka-CID3-IDz.html", "description": "Studio 25m2 aneks"}
    assert resolve_tags(offer_without)["primary"] == "kawalerka"

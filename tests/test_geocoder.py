"""Testy geocodera: limit geokodowań (MAX_NEW_GEOCODES) i fleksja polska.

Żaden test nie odpytuje live Nominatim — sieć jest blokowana przez podmianę
geolocator.geocode na funkcję rzucającą AssertionError.
"""

import json

import pytest

from geocoder import Geocoder, to_nominative, to_nominative_singular_feminine


@pytest.fixture
def geocoder(tmp_path):
    cache_file = tmp_path / "cache.json"
    cache_file.write_text(json.dumps({
        "Lipowa 14": {"lat": 51.2342, "lon": 22.5601},
    }), encoding="utf-8")
    geo = Geocoder(cache_file=str(cache_file))
    # Blokada sieci: każdy live call do Nominatim = fail testu
    geo.geolocator.geocode = lambda *a, **kw: (_ for _ in ()).throw(
        AssertionError("Test nie powinien odpytywać live Nominatim")
    )
    return geo


class TestGeocodingLimit:
    """FIX 2026-06-12: flaga _geocoding_limited była ustawiana w main.py,
    ale geocoder nigdy jej nie czytał — limit MAX_NEW_GEOCODES nie działał."""

    def test_limited_returns_none_for_uncached_address(self, geocoder):
        geocoder._geocoding_limited = True
        assert geocoder.geocode_address("Nieznana 1") is None

    def test_limited_does_not_poison_cache_with_none(self, geocoder):
        geocoder._geocoding_limited = True
        geocoder.geocode_address("Nieznana 1")
        # Adres NIE może trafić do cache jako None (zatrułby przyszłe skany)
        assert "Nieznana 1" not in geocoder.cache

    def test_limited_still_serves_cache_hits(self, geocoder):
        geocoder._geocoding_limited = True
        coords, meta = geocoder.geocode_address("Lipowa 14", return_meta=True)
        assert coords == {"lat": 51.2342, "lon": 22.5601}
        assert meta["cache_hit"] is True

    def test_not_limited_would_query_nominatim(self, geocoder):
        # Sanity check fixture'a: bez limitu zapytanie live faktycznie by poszło
        geocoder._geocoding_limited = False
        with pytest.raises(AssertionError):
            geocoder.geocode_address("Nieznana 1")


class TestNominative:
    """Regresja transformacji dopełniacz → mianownik (fleksja polska)."""

    @pytest.mark.parametrize("genitive,expected", [
        ("Puławskiej", "Puławska"),
        ("Puławskiej 10", "Puławska 10"),
        ("Spadowej", "Spadowa"),
        ("Pogodnej", "Pogodna"),
        ("Zachodniej", "Zachodnia"),
        ("Wołodyjowskiego", "Wołodyjowski"),
        ("Sympatycznej", "Sympatyczna"),
        ("Aleja Racławickich", "Aleja Racławickie"),
        # Bez transformacji
        ("Narutowicza", "Narutowicza"),
        ("Lipowa 14/2", "Lipowa 14/2"),
        ("", ""),
    ])
    def test_to_nominative(self, genitive, expected):
        assert to_nominative(genitive) == expected

    @pytest.mark.parametrize("plural,expected", [
        ("Kraśnickich", "Kraśnicka"),
        ("Nadbystrzyckich", "Nadbystrzycka"),
        ("Nadbystrzyckie", "Nadbystrzycka"),
        ("Kraśnickich 5", "Kraśnicka 5"),
        # Brak transformacji → pusty string (brak alternatywnego wariantu)
        ("Lipowa", ""),
        ("", ""),
    ])
    def test_to_nominative_singular_feminine(self, plural, expected):
        assert to_nominative_singular_feminine(plural) == expected

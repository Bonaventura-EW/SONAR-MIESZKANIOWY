"""Reguły dopasowania nazw z whitelisty OSM (FIX 2026-08-08).

Trzy razy z rzędu okazało się, że pojedyncze rozluźnienie dopasowania cofa
poprzednią naprawę: raz odmiana zamieniała osiedle w ulicę, raz podciąg robił
z ulicy dzielnicę, raz podciąg chronił czysty śmieć. Ten plik pilnuje podziału
ról, który z tego wyszedł:

  * `name_variants`  — strona ZAPYTANIA, wąska (tekst z ogłoszenia),
  * `index_variants` — strona SNAPSHOTU, szeroka (nazwy, które w OSM istnieją),
  * `is_street_name` / `is_known_street` — dopasowanie po PODCIĄGU członów,
  * `is_district_name` / `is_known_place` — dopasowanie PEŁNE.
"""

import pytest

from street_whitelist import (index_variants, is_district_name, is_known_place,
                              is_known_street, is_street_name, name_variants)


class TestWariantyNazwy:
    def test_zapytanie_nie_zamienia_liczby_mnogiej_na_pojedyncza(self):
        """Regresja: „Piastowskie" (osiedle) → „Piastowska" (realna, INNA ulica)."""
        assert 'piastowska' not in name_variants('Piastowskie')

    def test_indeks_zna_forme_pojedyncza(self):
        """Bez tego „Racławickiej" nie trafia w „Aleje Racławickie"."""
        assert 'raclawicka' in index_variants('Aleje Racławickie')

    def test_indeks_zawiera_wszystko_co_zapytanie(self):
        for name in ['Lipowa', 'Aleje Racławickie', 'Doktora Witolda Chodźki']:
            assert name_variants(name) <= index_variants(name)

    def test_whole_only_pomija_sam_ostatni_czlon(self):
        assert 'jezuickie' in index_variants('Rury Jezuickie')
        assert 'jezuickie' not in index_variants('Rury Jezuickie', whole_only=True)

    def test_pusta_nazwa_nie_wywraca(self):
        assert name_variants('') == set()
        assert index_variants('') == set()


class TestUlice:
    @pytest.mark.parametrize("name", [
        'Lipowa', 'Chodźki', 'Puławskiej',
        'Racławickiej',            # odmiana Alej Racławickich
        'Nałęczowska', 'Jezuicka', 'Jagiellońska',
    ])
    def test_realne_ulice(self, name):
        assert is_street_name(name) is True

    @pytest.mark.parametrize("name", [
        'Botanik', 'Piastowskie', 'Nowe', 'Wolne', 'Uniwersytetu Medycznego',
    ])
    def test_nie_ulice(self, name):
        assert is_street_name(name) is False


class TestDzielnice:
    @pytest.mark.parametrize("name", ['Wrotków', 'Rury', 'Prestige'])
    def test_realne_dzielnice(self, name):
        assert is_district_name(name) is True

    @pytest.mark.parametrize("name", ['Nałęczowska', 'Nałęczowskiej', 'Jezuicka', 'Jezuickiej'])
    def test_ulica_nie_jest_dzielnica(self, name):
        """Człon nazwy osiedla („Rury Jezuickie") nie czyni z ulicy dzielnicy —
        59 ofert przy ul. Nałęczowskiej wisiało na tym błędzie."""
        assert is_district_name(name) is False


class TestPelneKontraPodciag:
    def test_podciag_wpuszcza_skroty(self):
        """`is_known_street` celowo dopasowuje po podciągu — ogłoszenia skracają."""
        assert is_known_street('Chodźki') is True
        assert is_known_street('Nowe') is True     # podciąg „Nowe Sady"

    def test_pelne_dopasowanie_odrzuca_smiec(self):
        """`is_known_place` wymaga całości — sam człon „Nowe" to nie adres."""
        assert is_known_place('Nowe') is False
        assert is_known_place('Lipowa') is True

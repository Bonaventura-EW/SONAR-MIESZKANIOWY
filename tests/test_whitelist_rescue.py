"""Testy ścieżki ratunkowej parsera (route 4: `extract_from_whitelist`).

Ta ścieżka bierze nazwę ulicy z kluczy `geocoding_cache.json`, gdy trzy
wcześniejsze nic nie znalazły. Cache uczy się wszystkiego, co raz udało się
zgeokodować — łącznie z naszymi błędami — więc bez filtrów stawia pinezki
na opisie wnętrza („przytulna kawalerka") i na śmieciach („Wolne miejsca").
Zmierzone 2026-08-10: 87 z 694 aktywnych ofert miało adres z tej ścieżki,
z czego 27 etykiet w ogóle nie było ulicą, a 19 było przymiotnikiem.
"""

import pytest

from address_parser import AddressParser


@pytest.fixture(scope="module")
def parser():
    return AddressParser()


def _rescue(parser, text, streets):
    """Uruchamia route 4 na podstawionej whitelist (bez zależności od cache'u)."""
    original = parser._known_streets
    parser._known_streets = set(streets)
    try:
        result = parser.extract_from_whitelist(text)
    finally:
        parser._known_streets = original
    return (result or {}).get('full')


class TestRegulaOSM:
    """Reguła 1: kandydat musi być realną ulicą Lublina ze snapshotu OSM."""

    def test_odrzuca_smiec_z_cache(self, parser):
        assert _rescue(parser, 'Wolne miejsca parkingowe w garażu',
                       {'wolne', 'miejsca'}) is None

    def test_wpuszcza_realna_ulice(self, parser):
        assert _rescue(parser, 'Mieszkanie do wynajęcia Narutowicza, centrum',
                       {'narutowicza'}) == 'Narutowicza'

    def test_smiec_nie_wygrywa_z_ulica(self, parser):
        """Filtrujemy kandydatów, nie zwycięzcę — dłuższy śmieć („Uniwersytetu
        Medycznego") nie może przebić krótszej, realnej nazwy."""
        text = 'Mieszkanie Chodźki 3 dla studenta Uniwersytetu Medycznego'
        assert _rescue(parser, text,
                       {'chodźki', 'uniwersytetu medycznego'}) == 'Chodźki'


class TestRegulaPrzymiotnikowa:
    """Reguła 2: nazwa-przymiotnik przed rzeczownikiem mieszkaniowym to opis,
    nie adres. Nazwy ulic Lublina to w dużej części zwykłe przymiotniki."""

    @pytest.mark.parametrize("text", [
        'Przytulna kawalerka 38m2, centrum Lublina',
        'Mieszkanie w spokojnej okolicy, blisko centrum',
        'Bardzo ładna i cicha okolica na Czubach',
        'Ciepłe i słoneczne mieszkanie na parterze',
        'Pokój w zielonej, czystej, spokojnej dzielnicy LSM',
    ])
    def test_przymiotnik_nie_jest_adresem(self, parser, text):
        assert _rescue(parser, text,
                       {'przytulna', 'spokojna', 'spokojnej', 'cicha', 'słoneczne'}) is None

    def test_prefiks_ulicy_broni_adresu(self, parser):
        """„ul." gdziekolwiek w treści przebija regułę przymiotnikową."""
        text = 'ul. Cicha, mieszkanie z ogródkiem, 3 pokoje, cicha okolica'
        assert _rescue(parser, text, {'cicha'}) == 'Cicha'

    def test_nazwisko_przed_rzeczownikiem_zostaje(self, parser):
        """Sklejka tytułu z opisem („… | Narutowicza. Mieszkanie do wynajęcia")
        nie jest użyciem przymiotnikowym — dopełniacz nazwiska nim nie bywa."""
        text = 'Kawalerka z sypialnią | Śródmieście | Narutowicza. Mieszkanie do wynajęcia'
        assert _rescue(parser, text, {'narutowicza'}) == 'Narutowicza'

    def test_granica_zdania_przerywa_sasiedztwo(self, parser):
        """Kropka między nazwą a rzeczownikiem = dwa różne zdania."""
        text = 'Mieszkanie na Spokojnej. Kawalerka po remoncie'
        assert _rescue(parser, text, {'spokojnej'}) == 'Spokojnej'

    def test_rzeczownik_za_spojnikiem_tez_lapie(self, parser):
        """„w cichej i zielonej okolicy" — rzeczownik nie stoi tuż obok."""
        assert _rescue(parser, 'Mieszkanie w cichej i zielonej okolicy',
                       {'cicha', 'cichej'}) is None


class TestFiltrWeWszystkichSciezkach:
    """CLAUDE.md pkt 18: filtr musi obowiązywać we wszystkich czterech ścieżkach
    `extract_address`. Pierwsza wersja poprawki siedziała tylko w ratunkowej —
    i „Przytulna kawalerka 38 m²" dalej dostawała pinezkę, bo tę samą nazwę
    wyciągała ścieżka główna (zmierzone na produkcji 2026-08-11)."""

    def test_przymiotnik_odpada_takze_ze_sciezki_glownej(self, parser):
        text = 'Przytulna kawalerka 38m2, centrum Lublina, blisko KUL i UMCS'
        assert parser.extract_address(text) is None

    def test_adres_z_numerem_jest_zwolniony(self, parser):
        """„Przytulna 5" to adres, nie opis wnętrza — numer domu przebija regułę."""
        result = parser.extract_address('Mieszkanie ul. Przytulna 5, 2 pokoje')
        assert result and result['full'].startswith('Przytulna')

    def test_prefiks_broni_adresu_w_sciezce_glownej(self, parser):
        result = parser.extract_address('Mieszkanie przy ul. Cicha, cicha okolica')
        assert result and result['full'] == 'Cicha'


class TestGraniceZdan:
    """Przecinek rozdziela wyliczankę przymiotników, kropka i kreska — zdania."""

    def test_przecinek_nie_przerywa_wyliczanki(self, parser):
        """„cicha, bezpieczna i monitorowana okolica" — rzeczownik jest czwarty."""
        text = 'Mieszkanie w centrum, I piętro, cicha, bezpieczna i monitorowana okolica'
        assert parser.extract_address(text) is None

    def test_rzeczownik_tuz_za_przecinkiem(self, parser):
        assert parser.extract_address('Okolica bardzo spokojna, mieszkanie ciepłe') is None

    def test_kropka_przerywa_sasiedztwo(self, parser):
        """Sklejka tytułu z opisem zostaje adresem — to nie przymiotnik."""
        text = 'Kawalerka | Śródmieście | Narutowicza. Mieszkanie do wynajęcia'
        result = parser.extract_address(text)
        assert result and result['full'] == 'Narutowicza'


class TestWielkoscLiter:
    """Nazwa-przymiotnik pisana małą literą to zwykłe słowo, nie ulica.

    Rzeczowników opisujących mieszkanie nie da się wyliczyć w całości („nowe
    **wyposażenie**", „przy spokojnej **ulicy**", „spokojna, pracująca **para**"),
    więc dla nazw z `_ADJECTIVE_STREETS` decyduje też wielkość liter. Wymóg NIE
    obowiązuje pozostałych nazw — zmierzono, że zabiera pinezkę realnym adresom
    pisanym małą literą („mieszkanie na wynajem unicka").
    """

    @pytest.mark.parametrize("text", [
        'W kuchni znajduje się nowe wyposażenie, mieszkanie po remoncie',
        'Lokal znajduje się przy spokojnej ulicy, w pobliżu kawiarnie',
        'Mile widziana spokojna, pracująca para bądź studenci',
        'Mieszkanie w spokojnej części Lublina, cena najmu 3700 zł',
    ])
    def test_mala_litera_to_zwykle_slowo(self, parser, text):
        assert parser.extract_address(text) is None

    def test_wielka_litera_zostaje_adresem(self, parser):
        """Ten sam wyraz zapisany jak nazwa własna nadal jest ulicą."""
        text = 'Mieszkanie w kamienicy, ścisłe centrum, ulica Spokojna, budynek z kamerami'
        result = parser.extract_address(text)
        assert result and result['full'] == 'Spokojna'

    def test_nazwa_spoza_listy_przymiotnikow_przezywa_mala_litere(self, parser):
        """„unicka" nie jest przymiotnikiem — wielkość liter jej nie dotyczy."""
        assert _rescue(parser, 'Mieszkanie na wynajem unicka', {'unicka'}) == 'Unicka'


class TestWspolnyKontraktPrzymiotnikowy:
    """`is_adjectival_label` to jedyne publiczne wejście do reguły przymiotnikowej.

    Regresja historyczna: `address_migration` montowało przesłanki samo
    (`_boundary_text` + `_capitalized_words`) i raz po raz gubiło jedną, przez co
    podejmowało słabszą decyzję niż parser (FIX 2026-08-11). Publiczna metoda
    składa je w jednym miejscu — te testy pilnują, że wejście i wewnętrzne
    wyjście `extract_address` mówią to samo.
    """

    ADJ = [
        'Okolica jest bardzo spokojna i zielona, blisko sklepy',
        'W kuchni znajduje się nowe wyposażenie, mieszkanie po remoncie',
        'Mieszkanie w spokojnej części Lublina, cena 3700 zł',
    ]
    STREET = [
        ('Mieszkanie przy ul. Cicha, cicha okolica', 'cicha'),
        ('Ścisłe centrum, ulica Spokojna, budynek z kamerami', 'spokojna'),
    ]

    @pytest.mark.parametrize("text", ADJ)
    def test_wejscie_wykrywa_przymiotnik(self, parser, text):
        # nazwa, którą parser by tu zwrócił, gdyby nie reguła
        name = {'spokojna', 'nowe'}
        assert any(parser.is_adjectival_label(n, text) for n in name)
        # i faktycznie extract_address nic nie zwraca
        assert parser.extract_address(text) is None

    @pytest.mark.parametrize("text,name", STREET)
    def test_wejscie_przepuszcza_realny_adres(self, parser, text, name):
        assert parser.is_adjectival_label(name, text) is False

    def test_wejscie_zgodne_z_wynikiem_extract_address(self, parser):
        """Gdy `is_adjectival_label` mówi 'przymiotnik', `extract_address` nie
        może zwrócić tej nazwy — i odwrotnie. To gwarancja przeciw rozjazdowi."""
        for text in self.ADJ + [t for t, _ in self.STREET]:
            res = parser.extract_address(text)
            got = (res or {}).get('full', '').lower()
            if got:
                assert not parser.is_adjectival_label(got, text)

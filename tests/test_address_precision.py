"""Testy precyzji adresu i bezpieczników dodanych 2026-08-06.

Kontekst: mapa rysowała „kroplę" (adres dokładny) dla każdej oferty z numerem
domu, nawet gdy geokoder cofnął się do środka ulicy. Audyt 2026-08-06 pokazał,
że dotyczyło to 21 aktywnych ofert, a kolejne 51 miało numer dorobiony przez
parser z innego zdania.
"""

import json

import pytest

from main import SonarMieszkaniowy


@pytest.fixture
def agent(tmp_path):
    db = {'last_scan': None, 'next_scan': None, 'offers': []}
    data_file = tmp_path / 'offers.json'
    data_file.write_text(json.dumps(db), encoding='utf-8')
    return SonarMieszkaniowy(
        data_file=str(data_file),
        removed_file=str(tmp_path / 'removed.json'),
    )


COORDS = {'lat': 51.2465, 'lon': 22.5684}


class TestAddressPrecision:
    def test_bez_coords_to_none(self):
        assert SonarMieszkaniowy._address_precision(True, None) == 'none'

    def test_bez_numeru_to_street(self):
        assert SonarMieszkaniowy._address_precision(False, COORDS) == 'street'

    def test_z_numerem_i_trafionym_geokodem_to_exact(self):
        meta = {'number_fallback': False, 'cache_hit': True}
        assert SonarMieszkaniowy._address_precision(True, COORDS, meta) == 'exact'

    def test_fallback_geokodera_obniza_precyzje(self):
        """Geokoder nie znalazł numeru i zwrócił samą ulicę → to nie jest 'exact'."""
        meta = {'number_fallback': True, 'cache_hit': False}
        assert SonarMieszkaniowy._address_precision(True, COORDS, meta) == 'street'


class TestBackfillPrecision:
    """Uzupełnianie `precision` w starych rekordach — liczone offline z cache'u."""

    def _run(self, agent, offers, cache):
        agent.database['offers'] = offers
        agent.geocoder.cache = cache
        agent._backfill_address_precision()
        return [o['address'].get('precision') for o in offers]

    def test_punkt_rowny_geokodowi_ulicy_to_street(self, agent):
        """Coords identyczne z geokodem samej ulicy = środek ulicy, nie budynek."""
        offers = [{'id': 'a', 'address': {
            'full': 'Lubomelskiej 9', 'street': 'Lubomelskiej', 'number': '9',
            'has_number': True, 'coords': {'lat': 51.2509977, 'lon': 22.5509356}}}]
        cache = {'Lubomelskiej': {'lat': 51.2509977, 'lon': 22.5509356}}
        assert self._run(agent, offers, cache) == ['street']

    def test_punkt_inny_niz_ulica_zostaje_exact(self, agent):
        offers = [{'id': 'a', 'address': {
            'full': 'Lipowa 14', 'street': 'Lipowa', 'number': '14',
            'has_number': True, 'coords': {'lat': 51.2442975, 'lon': 22.5528556}}}]
        cache = {'Lipowa': {'lat': 51.2515424, 'lon': 22.5517915}}
        assert self._run(agent, offers, cache) == ['exact']

    def test_domyka_niespojne_has_number(self, agent):
        """has_number=True przy number=None (6 realnych ofert) → poprawiane."""
        offers = [{'id': 'a', 'address': {
            'full': 'Turkusowa', 'street': '', 'number': None,
            'has_number': True, 'coords': COORDS}}]
        self._run(agent, offers, {})
        assert offers[0]['address']['has_number'] is False
        assert offers[0]['address']['precision'] == 'street'

    def test_nie_nadpisuje_juz_ustawionej_precyzji(self, agent):
        offers = [{'id': 'a', 'address': {
            'full': 'Lipowa 14', 'street': 'Lipowa', 'number': '14',
            'has_number': True, 'precision': 'street', 'coords': COORDS}}]
        assert self._run(agent, offers, {}) == ['street']


class TestNoAddressAlert:
    """Bezpiecznik: regresja parsera nie może po cichu wyciąć ofert ze strony."""

    def test_zdrowy_skan_bez_alertu(self, agent):
        # realny skan 2026-08-06: 42 z 767 (5,5%)
        assert agent._no_address_alert(42, 767) is None

    def test_masowe_odrzucenie_daje_alert(self, agent):
        reason = agent._no_address_alert(400, 767)
        assert reason is not None
        assert '400' in reason and '767' in reason

    def test_maly_skan_nie_alarmuje(self, agent):
        """Przy garstce ofert odsetek jest statystycznie bez znaczenia."""
        assert agent._no_address_alert(10, 20) is None

    def test_prog_jest_wlaczny(self, agent):
        limit = int(767 * SonarMieszkaniowy.MAX_NO_ADDRESS_RATIO)
        assert agent._no_address_alert(limit, 767) is None
        assert agent._no_address_alert(limit + 20, 767) is not None


class TestNumberRetraction:
    """Korekta w dół: poprawiony parser musi umieć wycofać zmyślony numer."""

    def _existing(self):
        return {
            'id': 'x-CID3-IDx', 'url': 'https://www.olx.pl/d/oferta/x-CID3-IDx.html',
            'active': True, 'first_seen': '2026-08-01T10:00:00+02:00',
            'last_seen': '2026-08-01T10:00:00+02:00',
            'price': {'current': 2000, 'history': [2000], 'source': 'JSON-LD (OLX)'},
            'description': 'opis', 'days_active': 1,
            'address': {'full': 'Zana 2', 'street': 'Zana', 'number': '2',
                        'has_number': True, 'coords': {'lat': 51.24, 'lon': 22.53}},
        }

    def _new(self, address):
        return {
            'id': 'x-CID3-IDx', 'url': 'https://www.olx.pl/d/oferta/x-CID3-IDx.html',
            'price': {'current': 2000, 'media_info': 'brak informacji', 'source': 'JSON-LD (OLX)'},
            'description': 'opis', 'address': address,
        }

    def test_wycofuje_numer_gdy_ulica_ta_sama(self, agent):
        existing = self._existing()
        agent._update_existing_offer(existing, self._new({
            'full': 'Zana', 'street': 'Zana', 'number': None, 'has_number': False,
            'precision': 'street', 'coords': {'lat': 51.2401, 'lon': 22.5301}}))
        assert existing['address']['full'] == 'Zana'
        assert existing['address']['has_number'] is False
        # coords muszą pochodzić z NOWEGO geokodowania, nie ze zmyślonego budynku
        assert existing['address']['coords'] == {'lat': 51.2401, 'lon': 22.5301}

    def test_nie_przenosi_na_inna_ulice(self, agent):
        """Korekta działa tylko przy tej samej ulicy — inaczej stary adres zostaje."""
        existing = self._existing()
        agent._update_existing_offer(existing, self._new({
            'full': 'Lipowa', 'street': 'Lipowa', 'number': None, 'has_number': False}))
        assert existing['address']['full'] == 'Zana 2'

    def test_dodanie_numeru_dalej_dziala(self, agent):
        """Stara ścieżka „nowy adres ma numer, stary nie" ma zostać nietknięta."""
        existing = self._existing()
        existing['address'] = {'full': 'Zana', 'street': 'Zana', 'number': None, 'has_number': False}
        agent._update_existing_offer(existing, self._new({
            'full': 'Zana 12', 'street': 'Zana', 'number': '12', 'has_number': True,
            'coords': {'lat': 51.2402, 'lon': 22.5302}}))
        assert existing['address']['full'] == 'Zana 12'


class TestBackfillNaprawiaNiespojnosc:
    """`precision='none'` przy istniejących coords to niespójność do naprawy.

    Regresja z 2026-08-07: oferta z odzyskaną ulicą dostawała współrzędne, ale
    precyzja zostawała z czasów, gdy ich nie miała — mapa nie wiedziała, jakim
    markerem ją narysować.
    """

    def test_przelicza_none_gdy_sa_wspolrzedne(self, agent):
        agent.database['offers'] = [{'id': 'a', 'address': {
            'full': 'Piłsudskiego', 'street': 'Piłsudskiego', 'number': None,
            'has_number': False, 'precision': 'none', 'coords': COORDS}}]
        agent.geocoder.cache = {}
        agent._backfill_address_precision()
        assert agent.database['offers'][0]['address']['precision'] == 'street'

    def test_none_bez_wspolrzednych_zostaje(self, agent):
        agent.database['offers'] = [{'id': 'a', 'address': {
            'full': '', 'street': '', 'number': None,
            'has_number': False, 'precision': 'none'}}]
        agent.geocoder.cache = {}
        agent._backfill_address_precision()
        assert agent.database['offers'][0]['address']['precision'] == 'none'

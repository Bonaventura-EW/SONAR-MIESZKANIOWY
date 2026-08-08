"""Śmieciowa etykieta ustępuje realnej ulicy (FIX 2026-08-08).

Poprawka parsera sama z siebie nie dociera do bazy: „Kalina 38" ma numer, więc nie
łapało się na żaden z dotychczasowych warunków „lepszości" w `_update_existing_offer`,
a `_migrate_legacy_addresses` przelicza tylko wycofanie numeru przy TEJ SAMEJ ulicy.
Oferta zostawała ze zmyślonym adresem na zawsze — również nieaktywna, której scraper
w ogóle nie odwiedza.
"""

import json

import pytest

from address_migration import upgrade_junk_streets
from main import SonarMieszkaniowy


@pytest.fixture
def agent(tmp_path):
    db = {'last_scan': None, 'next_scan': None, 'offers': []}
    data_file = tmp_path / 'offers.json'
    data_file.write_text(json.dumps(db), encoding='utf-8')
    return SonarMieszkaniowy(data_file=str(data_file),
                             removed_file=str(tmp_path / 'removed.json'))


def _existing(full, coords=None, number=None):
    address = {'full': full, 'street': full.rsplit(' ', 1)[0] if number else full,
               'number': number, 'has_number': bool(number),
               'precision': 'exact' if coords and number else ('street' if coords else 'none')}
    if coords:
        address['coords'] = coords
    return {
        'id': 'x-CID3-IDx', 'url': 'https://www.olx.pl/d/oferta/x-CID3-IDx.html',
        'active': True, 'first_seen': '2026-08-01T10:00:00+02:00',
        'last_seen': '2026-08-01T10:00:00+02:00',
        'price': {'current': 2000, 'history': [2000], 'source': 'JSON-LD (OLX)'},
        'description': 'opis', 'days_active': 1, 'address': address,
    }


def _new(address):
    return {'id': 'x-CID3-IDx', 'url': 'https://www.olx.pl/d/oferta/x-CID3-IDx.html',
            'description': 'opis', 'address': address,
            'price': {'current': 2000, 'media_info': 'brak informacji', 'source': 'JSON-LD (OLX)'}}


class TestPodmianaWSkanie:
    def test_smiec_z_numerem_ustepuje_ulicy(self, agent):
        """„Kalina 38" (zmyślone) → „Niepodległości" (realna ulica z opisu)."""
        existing = _existing('Kalina 38', number='38')
        agent._update_existing_offer(existing, _new({
            'full': 'Niepodległości', 'street': 'Niepodległości', 'number': None,
            'has_number': False, 'precision': 'none'}))
        assert existing['address']['full'] == 'Niepodległości'
        assert existing['address']['has_number'] is False

    def test_realna_ulica_nie_ustepuje_smieciowi(self, agent):
        """Kierunek jest jednostronny — pinezka nigdy nie schodzi do śmiecia."""
        existing = _existing('Lipowa 10', number='10')
        agent._update_existing_offer(existing, _new({
            'full': 'Nowoczesne 3', 'street': 'Nowoczesne', 'number': '3',
            'has_number': True, 'precision': 'none'}))
        assert existing['address']['full'] == 'Lipowa 10'

    def test_nie_zabiera_pinezki_stojacej_dobrze(self, agent):
        """„Parysa Wynajmę" ma poprawny punkt 23 m od ul. Parysa — od sprzątania
        takich etykiet jest `_demote_non_street_pins`, które ZOSTAWIA pinezkę.
        Podmiana na inną ulicę zabrałaby ją, więc tu jej nie robimy."""
        existing = _existing('Parysa Wynajmę', coords={'lat': 51.24, 'lon': 22.53})
        agent._update_existing_offer(existing, _new({
            'full': 'Lipowa', 'street': 'Lipowa', 'number': None, 'has_number': False}))
        assert existing['address']['full'] == 'Parysa Wynajmę'
        assert existing['address']['coords'] == {'lat': 51.24, 'lon': 22.53}

    def test_nie_dziedziczy_coords_z_innej_ulicy(self, agent):
        """Stary punkt nie może pojechać za etykietą na INNĄ ulicę.

        Warunek „nowy ma numer, stary nie" podmienia adres; dotąd blok
        „zachowaj coords" doklejał wtedy punkt ul. Zana do etykiety „Lipowa 5",
        czyli stawiał pinezkę pod budynkiem przy zupełnie innej ulicy.
        """
        existing = _existing('Zana', coords={'lat': 51.2288, 'lon': 22.5301})
        agent._update_existing_offer(existing, _new({
            'full': 'Lipowa 5', 'street': 'Lipowa', 'number': '5', 'has_number': True}))
        assert existing['address']['full'] == 'Lipowa 5'
        assert 'coords' not in existing['address'], 'Pinezka ul. Zana pojechała na Lipową'

    def test_zachowuje_coords_przy_tej_samej_ulicy(self, agent):
        """Doprecyzowanie numeru na TEJ SAMEJ ulicy ma zostawić dotychczasowy punkt."""
        existing = _existing('Lipowa', coords={'lat': 51.2423, 'lon': 22.5479})
        agent._update_existing_offer(existing, _new({
            'full': 'Lipowa 5', 'street': 'Lipowa', 'number': '5', 'has_number': True}))
        assert existing['address']['coords'] == {'lat': 51.2423, 'lon': 22.5479}


class TestMigracjaWstecz:
    def _offer(self, full, description, active=False, coords=None):
        address = {'full': full, 'street': full, 'number': None, 'has_number': False,
                   'precision': 'none'}
        if coords:
            address['coords'] = coords
        return {'id': f'x-{full}', 'active': active, 'description': description,
                'address': address}

    def test_podmienia_etykiete_takze_nieaktywnym(self):
        offers = [self._offer('Sylwia 50', 'Mieszkanie przy ul. Jaczewskiego, 50 m2.')]
        result = upgrade_junk_streets(offers)
        assert result['to_fix'] == 1
        assert result['inactive_to_fix'] == 1
        assert offers[0]['address']['full'] == 'Jaczewskiego'

    def test_nie_rusza_oferty_z_pinezka(self):
        """Pinezka może stać dobrze mimo brzydkiej nazwy — to nie nasz przypadek."""
        offers = [self._offer('Sylwia 50', 'Mieszkanie przy ul. Jaczewskiego, 50 m2.',
                              coords={'lat': 51.25, 'lon': 22.57})]
        result = upgrade_junk_streets(offers)
        assert result['to_fix'] == 0
        assert result['has_coords'] == 1
        assert offers[0]['address']['full'] == 'Sylwia 50'

    def test_nie_rusza_realnej_ulicy(self):
        offers = [self._offer('Lipowa', 'Mieszkanie przy ul. Lipowej 10.')]
        result = upgrade_junk_streets(offers)
        assert result['to_fix'] == 0
        assert result['already_street'] == 1
        assert offers[0]['address']['full'] == 'Lipowa'

    def test_gdy_nowy_parse_tez_jest_smieciem_nic_nie_zmienia(self):
        offers = [self._offer('Nowoczesne 3', 'Nowoczesne 3 pokojowe mieszkanie do wynajęcia.')]
        result = upgrade_junk_streets(offers)
        assert result['to_fix'] == 0
        assert offers[0]['address']['full'] == 'Nowoczesne 3'

    def test_dokłada_pinezke_z_cache_geokodera(self):
        offers = [self._offer('Sylwia 50', 'Mieszkanie przy ul. Jaczewskiego, 50 m2.')]
        cache = {'Jaczewskiego': {'lat': 51.2531, 'lon': 22.5432}}
        result = upgrade_junk_streets(offers, geocoding_cache=cache)
        assert result['gained_coords'] == 1
        assert offers[0]['address']['coords'] == {'lat': 51.2531, 'lon': 22.5432}
        assert offers[0]['address']['precision'] == 'street'

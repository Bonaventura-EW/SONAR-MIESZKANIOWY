"""Tytuł ogłoszenia w popupie mapy (FIX 2026-08-09).

Popup pokazywał wyłącznie adres — a przy jednym adresie z kilkoma ofertami nie
dało się ich od siebie odróżnić. Tytuł jest teraz zapisywany w bazie przy skanie;
dla ofert sprzed tej zmiany odtwarzamy go ze slugu URL.
"""

import json

import pytest

from map_generator import display_title
from main import SonarMieszkaniowy


class TestDisplayTitle:
    def test_prawdziwy_tytul_wygrywa(self):
        offer = {'title': 'Pokój z balkonem – Ścisłe Centrum',
                 'url': 'https://www.olx.pl/d/oferta/cos-tam-CID3-IDabc.html'}
        assert display_title(offer) == 'Pokój z balkonem – Ścisłe Centrum'

    def test_fallback_ze_slugu_bez_ogona_cid(self):
        """Slug niesie treść i identyfikator — identyfikator nie jest tytułem."""
        offer = {'url': 'https://www.olx.pl/d/oferta/komfortowe-dwupokojowe-w-centrum-CID3-ID1blfy7.html'}
        assert display_title(offer) == 'Komfortowe dwupokojowe w centrum'

    def test_pusty_tytul_traktowany_jak_brak(self):
        offer = {'title': '   ',
                 'url': 'https://www.olx.pl/d/oferta/kawalerka-lsm-CID3-IDx1.html'}
        assert display_title(offer) == 'Kawalerka lsm'

    def test_brak_url_nie_wywraca(self):
        assert display_title({}) == ''

    def test_nie_gubi_tresci_gdy_slug_bez_cid(self):
        offer = {'url': 'https://www.olx.pl/d/oferta/mieszkanie-na-lsm.html'}
        assert display_title(offer) == 'Mieszkanie na lsm'


class TestTytulZapisywanyWBazie:
    @pytest.fixture
    def agent(self, tmp_path):
        data_file = tmp_path / 'offers.json'
        data_file.write_text(json.dumps({'last_scan': None, 'next_scan': None, 'offers': []}),
                             encoding='utf-8')
        return SonarMieszkaniowy(data_file=str(data_file),
                                 removed_file=str(tmp_path / 'removed.json'))

    def test_nowa_oferta_dostaje_tytul(self, agent):
        result = agent._process_offer({
            'title': 'Mieszkanie ul. Lipowa 10 — po remoncie',
            'description': 'Do wynajęcia mieszkanie przy ul. Lipowa 10.',
            'url': 'https://www.olx.pl/d/oferta/x-CID3-IDx.html',
            'official_price': 2500, 'price_source': 'json-ld'})
        assert result['title'] == 'Mieszkanie ul. Lipowa 10 — po remoncie'

    def test_istniejaca_oferta_dostaje_tytul_przy_aktualizacji(self, agent):
        """Bez tego prawdziwą nazwę miałyby tylko ogłoszenia dodane po zmianie."""
        existing = {
            'id': 'x-CID3-IDx', 'url': 'https://www.olx.pl/d/oferta/x-CID3-IDx.html',
            'active': True, 'first_seen': '2026-08-01T10:00:00+02:00',
            'last_seen': '2026-08-01T10:00:00+02:00', 'description': 'opis', 'days_active': 1,
            'price': {'current': 2000, 'history': [2000], 'source': 'JSON-LD (OLX)'},
            'address': {'full': 'Lipowa 10', 'street': 'Lipowa', 'number': '10',
                        'has_number': True, 'precision': 'exact'},
        }
        agent._update_existing_offer(existing, {
            'id': 'x-CID3-IDx', 'url': existing['url'], 'description': 'opis',
            'title': 'Świeży tytuł od sprzedawcy',
            'price': {'current': 2000, 'media_info': 'brak informacji', 'source': 'JSON-LD (OLX)'},
            'address': dict(existing['address'])})
        assert existing['title'] == 'Świeży tytuł od sprzedawcy'

    def test_brak_tytulu_nie_kasuje_zapisanego(self, agent):
        existing = {
            'id': 'x-CID3-IDx', 'url': 'https://www.olx.pl/d/oferta/x-CID3-IDx.html',
            'active': True, 'first_seen': '2026-08-01T10:00:00+02:00',
            'last_seen': '2026-08-01T10:00:00+02:00', 'description': 'opis', 'days_active': 1,
            'title': 'Stary, ale dobry',
            'price': {'current': 2000, 'history': [2000], 'source': 'JSON-LD (OLX)'},
            'address': {'full': 'Lipowa 10', 'street': 'Lipowa', 'number': '10',
                        'has_number': True, 'precision': 'exact'},
        }
        agent._update_existing_offer(existing, {
            'id': 'x-CID3-IDx', 'url': existing['url'], 'description': 'opis',
            'price': {'current': 2000, 'media_info': 'brak informacji', 'source': 'JSON-LD (OLX)'},
            'address': dict(existing['address'])})
        assert existing['title'] == 'Stary, ale dobry'

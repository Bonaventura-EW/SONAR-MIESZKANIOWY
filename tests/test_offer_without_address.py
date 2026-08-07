"""Oferta bez rozpoznanego adresu zostaje na stronie (FIX 2026-08-07).

Wcześniej `main._process_offer` zwracał None, więc ~34 ogłoszenia na skan
znikały bez śladu — a to normalne oferty, tylko bez ulicy w treści. Teraz
dostają pusty adres i trafiają do warstwy „bez lokacji"; zakładka debugowa
(`skipped_debug.html`) pokazuje je w sekcji „bez adresu".
"""

import json

import pytest

from main import SonarMieszkaniowy


@pytest.fixture
def agent(tmp_path):
    db = {'last_scan': None, 'next_scan': None, 'offers': []}
    data_file = tmp_path / 'offers.json'
    data_file.write_text(json.dumps(db), encoding='utf-8')
    return SonarMieszkaniowy(data_file=str(data_file),
                             removed_file=str(tmp_path / 'removed.json'))


def _raw(title, description, url='https://www.olx.pl/d/oferta/x-CID3-IDx.html'):
    return {'title': title, 'description': description, 'url': url,
            'official_price': 2500, 'price_source': 'json-ld'}


class TestOfertaBezAdresu:
    def test_oferta_bez_ulicy_nie_znika(self, agent):
        raw = _raw('Kawalerka dla studenta w świetnej lokalizacji!',
                   'Do wynajęcia przytulna kawalerka, blisko uczelni, umeblowana.')
        result = agent._process_offer(raw)

        assert result is not None, 'Oferta bez adresu nie może znikać ze strony'
        assert result['address']['full'] == ''
        assert result['address']['has_number'] is False
        assert result['address']['precision'] == 'none'
        assert 'coords' not in result['address']

    def test_oferta_z_adresem_dziala_po_staremu(self, agent):
        raw = _raw('Mieszkanie ul. Lipowa 10', 'Do wynajęcia mieszkanie przy ul. Lipowa 10.')
        result = agent._process_offer(raw)
        assert result is not None
        assert result['address']['full'] == 'Lipowa 10'

    def test_brak_ceny_nadal_odrzuca(self, agent):
        """Cena to inna sprawa — bez niej oferta dalej jest pomijana."""
        raw = {'title': 'Mieszkanie ul. Lipowa 10', 'description': 'Bez podanej ceny.',
               'url': 'https://www.olx.pl/d/oferta/y-CID3-IDy.html'}
        assert agent._process_offer(raw) is None

    def test_pusty_adres_nie_dziedziczy_cudzych_wspolrzednych(self, agent):
        """Dwie oferty bez adresu nie mogą się „dopasować" po pustym `full`."""
        agent.existing_offers_index = {
            'CID3-IDx': {'coordinates': {'lat': 51.25, 'lon': 22.57}, 'address_full': ''},
        }
        raw = _raw('Mieszkanie do wynajęcia', 'Ładne mieszkanie, dobra lokalizacja.')
        result = agent._process_offer(raw)
        assert result is not None
        assert 'coords' not in result['address'], 'Pusty adres odziedziczył cudze coords'

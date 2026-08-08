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


class TestSalvageStreetLabel:
    """Odzysk ulicy z zaśmieconej etykiety (FIX 2026-08-07).

    Dotyczy wyłącznie ofert, których geokoder nie umiał umiejscowić — nie może
    więc przesunąć żadnej istniejącej pinezki.
    """

    @pytest.mark.parametrize("label,expected", [
        ('PeowiakówZdjęcia są', 'Peowiaków'),          # sklejone tokeny
        ('Piłsudskiego Okna', 'Piłsudskiego'),
        ('Obywatelska piętro 10', 'Obywatelska'),
        ('Młodej Polski Powierzchnia', 'Młodej Polski'),
    ])
    def test_odzyskuje_ulice_z_doklejonym_smieciem(self, label, expected):
        assert SonarMieszkaniowy._salvage_street_label(label) == expected

    @pytest.mark.parametrize("label", [
        'Osiedle Klemensa Junoszy',   # cała nazwa jest poprawna — nie skracamy
        'Krakowskie Przedmieście',
        'Lipowa',
    ])
    def test_nie_skraca_poprawnej_nazwy(self, label):
        assert SonarMieszkaniowy._salvage_street_label(label) is None

    @pytest.mark.parametrize("label", ['Umowa', 'DOSTĘPNE', 'Nowoczesne', ''])
    def test_smiec_bez_ulicy_zwraca_none(self, label):
        assert SonarMieszkaniowy._salvage_street_label(label) is None

    def test_nie_akceptuje_krotkiego_jednoczlonowego_trafienia(self):
        """„Residence" ⊂ „Wikana Residence" — za słaba przesłanka na ulicę."""
        assert SonarMieszkaniowy._salvage_street_label('Residence Nowoczesne 3') is None


class TestOdzyskDocieraDoBazy:
    """Odzysk ulicy musi podmienić CAŁY adres, nie tylko dokleić współrzędne.

    Regresja z 2026-08-07: blok „uzupełnij brakujące coords" wstawiał punkt do
    starego adresu, przez co warunek „zdobyto współrzędne" już nie działał —
    oferta lądowała na mapie z etykietą „Piłsudskiego Okna" i `precision='none'`,
    czyli mapa nie wiedziała, jakim markerem ją narysować.
    """

    def _existing(self):
        return {
            'id': 'x-CID3-IDx', 'url': 'https://www.olx.pl/d/oferta/x-CID3-IDx.html',
            'active': True, 'first_seen': '2026-08-01T10:00:00+02:00',
            'last_seen': '2026-08-01T10:00:00+02:00',
            'price': {'current': 2000, 'history': [2000], 'source': 'JSON-LD (OLX)'},
            'description': 'opis', 'days_active': 1,
            'address': {'full': 'Piłsudskiego Okna', 'street': 'Piłsudskiego Okna',
                        'number': None, 'has_number': False, 'precision': 'none'},
        }

    def test_odzyskana_ulica_podmienia_caly_adres(self, agent):
        existing = self._existing()
        agent._update_existing_offer(existing, {
            'id': 'x-CID3-IDx', 'url': existing['url'], 'description': 'opis',
            'price': {'current': 2000, 'media_info': 'brak informacji', 'source': 'JSON-LD (OLX)'},
            'address': {'full': 'Piłsudskiego', 'street': 'Piłsudskiego', 'number': None,
                        'has_number': False, 'precision': 'street',
                        'coords': {'lat': 51.24, 'lon': 22.55}},
        })
        assert existing['address']['full'] == 'Piłsudskiego'
        assert existing['address']['precision'] == 'street'
        assert existing['address']['coords'] == {'lat': 51.24, 'lon': 22.55}

    def test_same_coords_bez_zmiany_adresu_domykaja_precyzje(self, agent):
        """Gdy adres zostaje ten sam, a dochodzą coords — precyzja nie może zostać 'none'."""
        existing = self._existing()
        agent._update_existing_offer(existing, {
            'id': 'x-CID3-IDx', 'url': existing['url'], 'description': 'opis',
            'price': {'current': 2000, 'media_info': 'brak informacji', 'source': 'JSON-LD (OLX)'},
            'address': {'full': 'Piłsudskiego Okna', 'street': 'Piłsudskiego Okna',
                        'number': None, 'has_number': False,
                        'coords': {'lat': 51.24, 'lon': 22.55}},
        })
        assert existing['address']['precision'] == 'street'

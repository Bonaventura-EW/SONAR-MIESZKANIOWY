"""Nominatim zwraca punkt ULICY na zapytanie o numer domu (FIX 2026-08-08).

Gdy numeru nie ma w OSM, Nominatim potrafi oddać punkt reprezentatywny ulicy
i zaraportować to jako trafienie. Braliśmy to za adres budynku — stąd pinezki
84–142 m od celu z kroplą „adres dokładny". Zmierzone na żywo:

    Lubomelskiej 9 -> house_number=None, road='Boczna Lubomelskiej'   (142 m)
    Lipowa 10      -> house_number='10', road='Lipowa'                (poprawnie)

Odrzucenie takiej odpowiedzi NIE gubi oferty: `_geocode_with_meta` leci dalej do
fallbacku „sama ulica", który zwraca ten sam punkt z `number_fallback=True`.
"""

import json

import pytest

from clean_geocoding_cache import find_street_level_number_keys
from geocoder import Geocoder


class _Location:
    """Minimalna atrapa geopy.Location — liczy się tylko `raw`."""

    def __init__(self, lat, lon, house_number=None, road=None):
        self.latitude, self.longitude = lat, lon
        address = {}
        if house_number is not None:
            address['house_number'] = house_number
        if road is not None:
            address['road'] = road
        self.raw = {'address': address}


class TestNumerZAdresu:
    @pytest.mark.parametrize("address,expected", [
        ('Lubomelskiej 9', '9'),
        ('Jemiołuszki 22B', '22B'),
        ('Wyżynna 33/40', '33/40'),
        ('Niepodległości 7d', '7d'),
        ('Lipowa', None),
        ('Krakowskie Przedmieście', None),
        ('', None),
    ])
    def test_wyciaga_numer_z_konca(self, address, expected):
        assert Geocoder._house_number(address) == expected


class TestPotwierdzenieNumeru:
    @pytest.mark.parametrize("got,wanted", [
        ('9', '9'),
        ('22B', '22b'),        # wielkość liter nie ma znaczenia
        ('2b', '2B'),
        ('33', '33/40'),       # OSM zna budynek, ogłoszenie podaje też lokal
        ('12', '12/5'),
    ])
    def test_potwierdzony(self, got, wanted):
        assert Geocoder._number_confirmed(_Location(51.24, 22.55, got), wanted) is True

    @pytest.mark.parametrize("got,wanted", [
        (None, '9'),           # realny przypadek „Lubomelskiej 9"
        ('7', '9'),            # inny budynek przy tej samej ulicy
        ('69', '69m'),         # „69m" to metraż, nie numer
    ])
    def test_niepotwierdzony(self, got, wanted):
        assert Geocoder._number_confirmed(_Location(51.24, 22.55, got), wanted) is False

    def test_odpowiedz_bez_adresu_nie_wywraca(self):
        loc = _Location(51.24, 22.55)
        loc.raw = {}
        assert Geocoder._number_confirmed(loc, '9') is False


class TestOdrzuceniePunktuUlicy:
    def _geo(self, tmp_path, location):
        cache = tmp_path / 'cache.json'
        cache.write_text('{}', encoding='utf-8')
        geo = Geocoder(cache_file=str(cache))
        geo.geolocator.geocode = lambda *a, **kw: location
        return geo

    def test_punkt_bez_numeru_jest_odrzucony(self, tmp_path):
        """Zapytanie miało numer, odpowiedź go nie ma → to poziom ulicy."""
        geo = self._geo(tmp_path, _Location(51.2509977, 22.5509356, road='Boczna Lubomelskiej'))
        assert geo._try_nominatim('Lubomelskiej 9') is None

    def test_punkt_z_numerem_przechodzi(self, tmp_path):
        geo = self._geo(tmp_path, _Location(51.24515, 22.5479, house_number='10', road='Lipowa'))
        assert geo._try_nominatim('Lipowa 10') == {'lat': 51.24515, 'lon': 22.5479}

    def test_zapytanie_bez_numeru_nie_jest_walidowane(self, tmp_path):
        """Sama ulica — nie ma czego potwierdzać, odpowiedź przechodzi."""
        geo = self._geo(tmp_path, _Location(51.2423, 22.5479, road='Lipowa'))
        assert geo._try_nominatim('Lipowa') == {'lat': 51.2423, 'lon': 22.5479}

    def test_odrzucony_numer_spada_do_fallbacku_ulicy(self, tmp_path):
        """Kluczowa własność: oferta nie znika, tylko traci udawaną precyzję."""
        cache = tmp_path / 'cache.json'
        cache.write_text(json.dumps({'Lubomelskiej': {'lat': 51.2509977, 'lon': 22.5509356}}),
                         encoding='utf-8')
        geo = Geocoder(cache_file=str(cache))
        geo.geolocator.geocode = lambda *a, **kw: _Location(
            51.2509977, 22.5509356, road='Boczna Lubomelskiej')
        coords, meta = geo._geocode_with_meta('Lubomelskiej 9')
        assert coords == {'lat': 51.2509977, 'lon': 22.5509356}
        assert meta['number_fallback'] is True, 'Precyzja musi spaść do poziomu ulicy'


class TestZatrutyCache:
    def test_znajduje_klucz_z_numerem_na_punkcie_ulicy(self):
        cache = {
            'Lubomelskiej': {'lat': 51.25, 'lon': 22.55},
            'Lubomelskiej 9': {'lat': 51.25, 'lon': 22.55},      # ten sam punkt
            'Lipowa': {'lat': 51.24, 'lon': 22.54},
            'Lipowa 10': {'lat': 51.2451, 'lon': 22.5479},        # realny budynek
            '__null_timestamps__': {'X': 1},
        }
        assert find_street_level_number_keys(cache) == [('Lubomelskiej 9', 'Lubomelskiej')]

    def test_brak_wpisu_ulicy_nic_nie_znajduje(self):
        assert find_street_level_number_keys({'Lipowa 10': {'lat': 51.2, 'lon': 22.5}}) == []

    def test_null_nie_wywraca(self):
        assert find_street_level_number_keys({'Lipowa': None, 'Lipowa 10': None}) == []


class TestPrecyzjaPrzezywaSkan:
    """Reużycie punktu nie może kasować uczciwego 'street' (FIX 2026-08-08).

    ~70% ofert nie dotyka geokodera — `_process_offer` bierze ich współrzędne
    z bazy. Bez meta z geokodera `_address_precision` liczyło precyzję od zera
    i oferta z numerem wracała jako 'exact', mimo że jej punkt to środek ulicy.
    """

    @pytest.fixture
    def agent(self, tmp_path):
        from main import SonarMieszkaniowy
        data_file = tmp_path / 'offers.json'
        data_file.write_text(json.dumps({'last_scan': None, 'next_scan': None, 'offers': []}),
                             encoding='utf-8')
        return SonarMieszkaniowy(data_file=str(data_file),
                                 removed_file=str(tmp_path / 'removed.json'))

    def test_reuzyty_punkt_zachowuje_street(self, agent):
        coords = {'lat': 51.2509977, 'lon': 22.5509356}
        agent.existing_offers_index = {'CID3-IDx': {
            'coordinates': coords, 'address_full': 'Lubomelskiej 9',
            'address': {'full': 'Lubomelskiej 9', 'precision': 'street'},
        }}
        result = agent._process_offer({
            'title': 'Mieszkanie ul. Lubomelskiej 9',
            'description': 'Do wynajęcia mieszkanie przy ul. Lubomelskiej 9.',
            'url': 'https://www.olx.pl/d/oferta/x-CID3-IDx.html',
            'official_price': 2500, 'price_source': 'json-ld'})
        assert result['address']['full'] == 'Lubomelskiej 9'
        assert result['address']['precision'] == 'street'

    def test_reuzyty_punkt_z_exact_zostaje_exact(self, agent):
        coords = {'lat': 51.2451, 'lon': 22.5479}
        agent.existing_offers_index = {'CID3-IDy': {
            'coordinates': coords, 'address_full': 'Lipowa 10',
            'address': {'full': 'Lipowa 10', 'precision': 'exact'},
        }}
        result = agent._process_offer({
            'title': 'Mieszkanie ul. Lipowa 10',
            'description': 'Do wynajęcia mieszkanie przy ul. Lipowa 10.',
            'url': 'https://www.olx.pl/d/oferta/y-CID3-IDy.html',
            'official_price': 2500, 'price_source': 'json-ld'})
        assert result['address']['precision'] == 'exact'


class TestObnizeniePrecyzjiWSkanie:
    @pytest.fixture
    def agent(self, tmp_path):
        from main import SonarMieszkaniowy
        data_file = tmp_path / 'offers.json'
        data_file.write_text(json.dumps({'last_scan': None, 'next_scan': None, 'offers': []}),
                             encoding='utf-8')
        cache_file = tmp_path / 'cache.json'
        cache_file.write_text(json.dumps({
            'Lubomelskiej': {'lat': 51.25, 'lon': 22.55},
            'Lubomelskiej 9': {'lat': 51.25, 'lon': 22.55},
        }), encoding='utf-8')
        a = SonarMieszkaniowy(data_file=str(data_file), removed_file=str(tmp_path / 'removed.json'))
        a.geocoder = Geocoder(cache_file=str(cache_file))
        return a

    def _offer(self, full, precision, coords):
        return {'id': f'x-{full}', 'active': True,
                'address': {'full': full, 'street': full.rsplit(' ', 1)[0], 'number': '9',
                            'has_number': True, 'precision': precision, 'coords': coords}}

    def test_obniza_exact_i_czysci_cache(self, agent):
        agent.database['offers'] = [self._offer('Lubomelskiej 9', 'exact', {'lat': 51.25, 'lon': 22.55})]
        agent._downgrade_street_level_pins()
        addr = agent.database['offers'][0]['address']
        assert addr['precision'] == 'street'
        assert addr['coords'] == {'lat': 51.25, 'lon': 22.55}, 'Pinezka nie może zniknąć ani się ruszyć'
        assert 'Lubomelskiej 9' not in agent.geocoder.cache
        assert 'Lubomelskiej' in agent.geocoder.cache, 'Punkt ulicy zostaje — z niego żyje fallback'

    def test_jest_idempotentne(self, agent):
        agent.database['offers'] = [self._offer('Lubomelskiej 9', 'exact', {'lat': 51.25, 'lon': 22.55})]
        agent._downgrade_street_level_pins()
        agent._downgrade_street_level_pins()
        assert agent.database['offers'][0]['address']['precision'] == 'street'

"""Bilans „dlaczego oferta nie jest na mapie" musi się domykać (FIX 2026-08-09).

Zakładka debugowa obiecywała „oferty, które scraper pobrał, ale nie trafiły na
mapę", a pokazywała wyłącznie te, którym parser nie znalazł ULICY — 28 z 111.
Reszta (etykieta nie do odczytania, nazwa obszaru zamiast punktu, brak geokodu)
nie była nigdzie policzona, bo współrzędne zdejmują im kroki uruchamiane PO pętli
skanu, więc liczniki z tej pętli nie mogły ich zobaczyć.

Dlatego bilans liczymy z KOŃCOWEGO stanu bazy i pilnujemy równania:

    aktywne = na mapie + suma czterech kategorii
"""

import json

import pytest

from main import SonarMieszkaniowy
from skipped_debug_generator import (OFF_MAP_CATEGORIES, SKIPPED_CATEGORIES,
                                     CATEGORY_LABELS, generate_skipped_debug_page)


@pytest.fixture
def agent(tmp_path):
    data_file = tmp_path / 'offers.json'
    data_file.write_text(json.dumps({'last_scan': None, 'next_scan': None, 'offers': []}),
                         encoding='utf-8')
    (tmp_path / 'skipped_offers_sample.json').write_text(
        json.dumps({'scan_timestamp': '2026-08-09T10:00:00+02:00',
                    'counts': {'duplicate': 59, 'no_price': 1}, 'samples': {}}),
        encoding='utf-8')
    return SonarMieszkaniowy(data_file=str(data_file),
                             removed_file=str(tmp_path / 'removed.json'))


def _offer(oid, full, coords=None, active=True):
    address = {'full': full, 'street': full, 'number': None, 'has_number': False,
               'precision': 'street' if coords else 'none'}
    if coords:
        address['coords'] = coords
    return {'id': oid, 'url': f'https://www.olx.pl/d/oferta/{oid}.html',
            'active': active, 'description': 'opis oferty', 'address': address}


COORDS = {'lat': 51.2465, 'lon': 22.5684}


class TestKlasyfikacja:
    @pytest.mark.parametrize("full,expected", [
        ('', 'no_address'),
        ('Lipowa', 'no_coords'),                 # realna ulica — winny geokoder
        ('Chodźki', 'no_coords'),
        ('Wrotków', 'area_only'),                # dzielnica z OSM
        ('Osiedle Prestige', 'area_only'),
        ('Brzeska', 'no_coords'),
        ('King Size 180x', 'not_a_street'),      # śmieć z ogłoszenia
        ('Duże łóżko 120', 'not_a_street'),
        ('Wolne', 'not_a_street'),
    ])
    def test_przyczyna_braku_pinezki(self, agent, full, expected):
        assert agent._classify_map_gap({'full': full, 'street': full}) == expected

    def test_pusty_adres_nie_wywraca(self, agent):
        assert agent._classify_map_gap({}) == 'no_address'


class TestBilans:
    def test_suma_kategorii_rowna_sie_ofertom_poza_mapa(self, agent):
        agent.database['offers'] = [
            _offer('a', 'Lipowa 10', COORDS),      # na mapie
            _offer('b', 'Chodźki', COORDS),        # na mapie
            _offer('c', ''),                       # no_address
            _offer('d', 'King Size 180x'),         # not_a_street
            _offer('e', 'Wrotków'),                # area_only
            _offer('f', 'Lipowa'),                 # no_coords
        ]
        agent._write_map_gap_breakdown()
        gap = json.loads((agent.data_file.parent / 'skipped_offers_sample.json')
                         .read_text(encoding='utf-8'))['map_gap']
        assert gap['active'] == 6
        assert gap['on_map'] == 2
        assert gap['off_map'] == 4
        assert gap['counts'] == {'no_address': 1, 'not_a_street': 1,
                                 'area_only': 1, 'no_coords': 1}
        assert sum(gap['counts'].values()) == gap['off_map']

    def test_nieaktywne_nie_wchodza_do_bilansu(self, agent):
        agent.database['offers'] = [
            _offer('a', 'Lipowa 10', COORDS),
            _offer('z', 'Wolne', active=False),
        ]
        agent._write_map_gap_breakdown()
        gap = json.loads((agent.data_file.parent / 'skipped_offers_sample.json')
                         .read_text(encoding='utf-8'))['map_gap']
        assert gap['active'] == 1 and gap['off_map'] == 0

    def test_nie_kasuje_licznikow_ze_skanu(self, agent):
        """Bilans dopisuje się do pliku, nie nadpisuje go."""
        agent.database['offers'] = [_offer('a', 'Lipowa 10', COORDS)]
        agent._write_map_gap_breakdown()
        data = json.loads((agent.data_file.parent / 'skipped_offers_sample.json')
                          .read_text(encoding='utf-8'))
        assert data['counts']['duplicate'] == 59
        assert data['counts']['no_price'] == 1
        assert 'map_gap' in data

    def test_limit_probek_nie_wysadza_pliku(self, agent):
        agent.database['offers'] = [_offer(f'x{i}', 'Wolne') for i in range(80)]
        agent._write_map_gap_breakdown()
        gap = json.loads((agent.data_file.parent / 'skipped_offers_sample.json')
                         .read_text(encoding='utf-8'))['map_gap']
        assert gap['counts']['not_a_street'] == 80, 'Licznik ma być pełny…'
        assert len(gap['samples']['not_a_street']) == SonarMieszkaniowy.MAP_GAP_SAMPLE_LIMIT, \
            '…a lista przykładów przycięta'


class TestStronaDebug:
    def _page(self, tmp_path, agent):
        agent._write_map_gap_breakdown()
        out = tmp_path / 'debug.html'
        assert generate_skipped_debug_page(
            sample_path=str(agent.data_file.parent / 'skipped_offers_sample.json'),
            output_path=str(out)) is True
        return out.read_text(encoding='utf-8')

    def test_pokazuje_wszystkie_szesc_kategorii(self, tmp_path, agent):
        agent.database['offers'] = [
            _offer('c', ''), _offer('d', 'King Size 180x'),
            _offer('e', 'Wrotków'), _offer('f', 'Lipowa'),
        ]
        page = self._page(tmp_path, agent)
        for cat in OFF_MAP_CATEGORIES + SKIPPED_CATEGORIES:
            assert f'stat-card {cat}' in page, f'Brak karty dla kategorii {cat}'
            assert CATEGORY_LABELS[cat]['label'] in page

    def test_rachunek_oznaczony_jako_domkniety(self, tmp_path, agent):
        agent.database['offers'] = [_offer('a', 'Lipowa 10', COORDS), _offer('c', '')]
        page = self._page(tmp_path, agent)
        assert 'reconciliation ok' in page
        assert 'bilans się NIE domyka' not in page

    def test_stary_plik_bez_bilansu_nadal_dziala(self, tmp_path):
        """Wsteczna zgodność: `map_gap` może jeszcze nie istnieć w pliku."""
        sample = tmp_path / 's.json'
        sample.write_text(json.dumps({'scan_timestamp': '2026-08-09T10:00:00+02:00',
                                      'counts': {'duplicate': 3}, 'samples': {}}),
                          encoding='utf-8')
        out = tmp_path / 'debug.html'
        assert generate_skipped_debug_page(sample_path=str(sample), output_path=str(out)) is True
        # Sam blok CSS zostaje; chodzi o to, żeby nie renderować rachunku z pustych danych.
        assert '<p class="reconciliation' not in out.read_text(encoding='utf-8')

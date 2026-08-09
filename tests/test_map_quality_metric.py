"""Jakość mapy jako metryka skanu (FIX 2026-08-09).

Przez kilka rund każdą zmianę parsera i geokodera trzeba było mierzyć doraźnym
skryptem („ile pinezek dokładnych ubyło?"). Teraz liczba jedzie do
`scan_history.json` przy każdym skanie i ląduje na wykresie w monitoringu, więc
regresja zgłasza się sama.
"""

import json

import pytest

from monitoring_generator import generate_monitoring_data
from main import SonarMieszkaniowy


@pytest.fixture
def agent(tmp_path):
    data_file = tmp_path / 'offers.json'
    data_file.write_text(json.dumps({'last_scan': None, 'next_scan': None, 'offers': []}),
                         encoding='utf-8')
    return SonarMieszkaniowy(data_file=str(data_file),
                             removed_file=str(tmp_path / 'removed.json'))


def _offer(oid, precision, coords=None, active=True):
    address = {'full': 'Lipowa 10', 'street': 'Lipowa', 'number': '10',
               'has_number': True, 'precision': precision}
    if coords:
        address['coords'] = coords
    return {'id': oid, 'url': f'https://www.olx.pl/d/oferta/{oid}.html',
            'active': active, 'description': 'opis', 'address': address}


COORDS = {'lat': 51.2465, 'lon': 22.5684}


class TestZliczaniePrecyzji:
    def test_liczy_podzial_na_dokladne_uliczne_i_bez_pinezki(self, agent):
        agent.database['offers'] = [
            _offer('a', 'exact', COORDS), _offer('b', 'exact', COORDS),
            _offer('c', 'street', COORDS), _offer('d', 'none'),
        ]
        agent._write_map_gap_breakdown()
        q = agent.map_quality_stats
        assert q['precision'] == {'exact': 2, 'street': 1, 'none': 1}
        assert q['active'] == 4 and q['on_map'] == 3 and q['off_map'] == 1

    def test_brak_precyzji_liczony_jako_none(self, agent):
        """Stary rekord bez pola `precision` nie może wywrócić metryki."""
        offer = _offer('x', 'exact')
        del offer['address']['precision']
        agent.database['offers'] = [offer]
        agent._write_map_gap_breakdown()
        assert agent.map_quality_stats['precision'] == {'exact': 0, 'street': 0, 'none': 1}

    def test_nieaktywne_pomijane(self, agent):
        agent.database['offers'] = [_offer('a', 'exact', COORDS),
                                    _offer('z', 'exact', COORDS, active=False)]
        agent._write_map_gap_breakdown()
        assert agent.map_quality_stats['precision']['exact'] == 1

    def test_metryka_nie_zawiera_probek(self, agent):
        """Do historii skanów idą liczby, nie lista ofert — plik ma nie puchnąć."""
        agent.database['offers'] = [_offer('a', 'none')]
        agent._write_map_gap_breakdown()
        assert 'samples' not in agent.map_quality_stats


class TestSeriaDoWykresu:
    def _history(self, tmp_path, scans):
        path = tmp_path / 'scan_history.json'
        path.write_text(json.dumps(scans), encoding='utf-8')  # historia to lista
        return path

    def _scan(self, ts, exact, street, none, on_map, off_map):
        return {'timestamp': ts, 'status': 'completed', 'total_duration': 100,
                'stats': {'raw_offers': 700, 'processed': 650, 'new': 1,
                          'map_quality': {'active': exact + street + none,
                                          'on_map': on_map, 'off_map': off_map,
                                          'precision': {'exact': exact, 'street': street,
                                                        'none': none}}}}

    def test_liczy_udzial_procentowy(self, tmp_path, monkeypatch):
        import paths
        history = self._history(tmp_path, [self._scan('2026-08-09T10:00:00+02:00',
                                                      247, 355, 113, 602, 113)])
        out = tmp_path / 'monitoring_data.json'
        monkeypatch.setattr(paths, 'SCAN_HISTORY_JSON', str(history))
        monkeypatch.setattr(paths, 'DOCS_MONITORING_JSON', str(out))
        generate_monitoring_data()
        series = json.loads(out.read_text(encoding='utf-8'))['charts']['map_quality']
        assert len(series) == 1
        assert series[0]['exact'] == 247 and series[0]['off_map'] == 113
        assert series[0]['exact_pct'] == pytest.approx(34.5, abs=0.1)
        assert series[0]['off_map_pct'] == pytest.approx(15.8, abs=0.1)

    def test_stare_skany_bez_metryki_sa_pomijane(self, tmp_path, monkeypatch):
        """Historia sprzed tej zmiany nie ma `map_quality` — nie zmyślamy zer."""
        import paths
        old = {'timestamp': '2026-08-01T10:00:00+02:00', 'status': 'completed',
               'total_duration': 100, 'stats': {'raw_offers': 700}}
        history = self._history(tmp_path, [old, self._scan('2026-08-09T10:00:00+02:00',
                                                           10, 5, 5, 15, 5)])
        out = tmp_path / 'monitoring_data.json'
        monkeypatch.setattr(paths, 'SCAN_HISTORY_JSON', str(history))
        monkeypatch.setattr(paths, 'DOCS_MONITORING_JSON', str(out))
        generate_monitoring_data()
        series = json.loads(out.read_text(encoding='utf-8'))['charts']['map_quality']
        assert len(series) == 1, 'Skan bez metryki nie może trafić na wykres'

    def test_zero_ofert_nie_dzieli_przez_zero(self, tmp_path, monkeypatch):
        import paths
        history = self._history(tmp_path, [self._scan('2026-08-09T10:00:00+02:00',
                                                      0, 0, 0, 0, 0)])
        out = tmp_path / 'monitoring_data.json'
        monkeypatch.setattr(paths, 'SCAN_HISTORY_JSON', str(history))
        monkeypatch.setattr(paths, 'DOCS_MONITORING_JSON', str(out))
        generate_monitoring_data()
        series = json.loads(out.read_text(encoding='utf-8'))['charts']['map_quality']
        assert series[0]['exact_pct'] == 0

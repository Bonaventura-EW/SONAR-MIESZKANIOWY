"""Testy api_generator: mapowanie skanów na status UI/powiadomienia.

FIX 2026-06-12: skan zablokowany przez OLX (0 ofert, ochrona przed dezaktywacją)
loguje błąd do scan_history — API musi pokazać warning, nie "✅ brak zmian".
"""

import pytest

from api_generator import APIGenerator


@pytest.fixture
def gen(tmp_path):
    return APIGenerator(output_dir=str(tmp_path))


def _scan(status='completed', errors=None, stats=None):
    return {
        'timestamp': '2026-06-12T09:17:00+02:00',
        'status': status,
        'errors': errors or [],
        'stats': stats or {},
        'total_duration': 25.0,
    }


class TestBlockedScanIsWarning:
    def test_completed_scan_with_block_error_is_warning(self, gen):
        scan = _scan(errors=[{'message': 'Scraper zwrócił 0 ofert — blokada OLX', 'timestamp': 'x'}],
                     stats={'raw_offers': 0, 'processed': 0, 'new': 0})
        out = gen._format_scan_for_api(scan)
        assert out['uiStatus'] == 'warning'
        assert 'blokada OLX' in out['failureReason']
        assert out['notification']['title'].startswith('⚠️')

    def test_clean_scan_is_success(self, gen):
        scan = _scan(stats={'raw_offers': 527, 'processed': 470, 'new': 6})
        out = gen._format_scan_for_api(scan)
        assert out['uiStatus'] == 'success'
        assert out['failureReason'] is None

    def test_failed_scan_is_failed(self, gen):
        scan = _scan(status='failed', errors=[{'message': 'wyjątek', 'timestamp': 'x'}])
        out = gen._format_scan_for_api(scan)
        assert out['uiStatus'] == 'failed'

    def test_system_status_degraded_on_errors(self, gen):
        scan = _scan(errors=[{'message': 'blokada', 'timestamp': 'x'}])
        assert gen._determine_system_status(scan, {'success_rate': 100}) == 'degraded'

    def test_short_format_warning(self, gen):
        scan = _scan(errors=[{'message': 'blokada', 'timestamp': 'x'}])
        short = gen._format_scan_short(scan)
        assert short['uiStatus'] == 'warning'
        assert short['hasErrors'] is True

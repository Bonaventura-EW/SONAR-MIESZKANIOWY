"""Testy scan_logger: wykrywanie zablokowanego skanu i statystyki dashboardu."""

import json

from scan_logger import ScanLogger, is_block_scan


def _scan(status='completed', raw_offers=700, duration=135.0, errors=None):
    return {
        'status': status,
        'total_duration': duration,
        'stats': {'raw_offers': raw_offers},
        'errors': errors or [],
    }


def test_is_block_scan_detects_zero_offers_with_error():
    blocked = _scan(raw_offers=0, duration=2.5, errors=[{'message': 'blokada OLX'}])
    assert is_block_scan(blocked) is True


def test_is_block_scan_false_for_healthy():
    assert is_block_scan(_scan()) is False


def test_is_block_scan_false_for_zero_offers_without_error():
    # 0 ofert bez wpisu w errors (teoretyczny pusty listing) — nie blokada.
    assert is_block_scan(_scan(raw_offers=0, errors=[])) is False


def test_statistics_split_success_warning_failure(tmp_path):
    history = [
        _scan(),                                                    # sukces
        _scan(),                                                    # sukces
        _scan(errors=[{'message': 'blokada'}], raw_offers=0, duration=2.5),  # ostrzeżenie/blokada
        _scan(status='failed', errors=[{'message': 'wyjątek'}]),    # awaria
    ]
    log_file = tmp_path / 'scan_history.json'
    log_file.write_text(json.dumps(history), encoding='utf-8')
    stats = ScanLogger(log_file=str(log_file)).get_statistics()

    assert stats['total_scans'] == 4
    assert stats['successful'] == 2          # completed i zero błędów
    assert stats['warnings'] == 1            # completed z błędem (blokada)
    assert stats['failed'] == 2              # wszystko poza sukcesem


def test_statistics_exclude_block_scans_from_averages(tmp_path):
    history = [
        _scan(raw_offers=700, duration=130.0),
        _scan(raw_offers=720, duration=140.0),
        # 3 blokady: 0 ofert, ~2.5 s, z błędem — nie wchodzą do średnich
        _scan(raw_offers=0, duration=2.5, errors=[{'message': 'blokada'}]),
        _scan(raw_offers=0, duration=2.5, errors=[{'message': 'blokada'}]),
        _scan(raw_offers=0, duration=2.5, errors=[{'message': 'blokada'}]),
    ]
    log_file = tmp_path / 'scan_history.json'
    log_file.write_text(json.dumps(history), encoding='utf-8')
    stats = ScanLogger(log_file=str(log_file)).get_statistics()

    assert stats['avg_offers_found'] == 710.0        # (700+720)/2, bez zer z blokad
    assert stats['avg_duration'] == 135.0            # (130+140)/2, bez ~2.5 s blokad

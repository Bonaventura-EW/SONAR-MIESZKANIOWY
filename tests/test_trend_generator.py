"""Testy rekonstrukcji indeksu podaży (trend_generator)."""

import json
from datetime import date

import pytest

import trend_generator as gen


def _offer(first_seen, last_seen, active=False):
    return {
        'first_seen': f'{first_seen}T10:00:00+02:00',
        'last_seen': f'{last_seen}T18:00:00+02:00',
        'active': active,
    }


def _by_day(series):
    """[[ms, val], ...] -> {date: val} — czytelniejsze asercje."""
    from datetime import datetime
    return {datetime.fromtimestamp(ms / 1000).date(): val for ms, val in series}


def test_empty_input():
    assert gen.build_series([]) == []
    assert gen.build_outflow([]) is None
    assert gen.compute_deltas([]) == {}


def test_series_counts_living_offers_per_day():
    offers = [
        _offer('2026-05-16', '2026-05-18'),           # żyje 16–18
        _offer('2026-05-17', '2026-05-17'),           # tylko 17
        _offer('2026-05-18', '2026-05-19', True),     # aktywna → do ostatniego dnia
    ]
    days = _by_day(gen.build_series(offers))
    assert days[date(2026, 5, 16)] == 1
    assert days[date(2026, 5, 17)] == 2
    assert days[date(2026, 5, 18)] == 2
    assert days[date(2026, 5, 19)] == 1
    assert max(days) == date(2026, 5, 19)   # koniec = najświeższy last_seen


def test_series_cuts_off_unreliable_history():
    """Dni sprzed RELIABLE_START nie trafiają do serii (zaniżone dane)."""
    offers = [_offer('2026-04-29', '2026-05-20', True)]
    days = _by_day(gen.build_series(offers))
    assert min(days) == gen.RELIABLE_START
    assert days[gen.RELIABLE_START] == 1


def test_series_survives_broken_dates():
    offers = [
        _offer('2026-05-16', '2026-05-17'),
        {'first_seen': 'nie-data', 'last_seen': '2026-05-17T10:00:00', 'active': False},
        {'active': True},                                    # brak dat
    ]
    days = _by_day(gen.build_series(offers))
    assert days[date(2026, 5, 16)] == 1


def test_span_end_before_start_is_clamped():
    """last_seen < first_seen (śmieć w bazie) nie tworzy ujemnego okresu."""
    offers = [
        _offer('2026-05-18', '2026-05-17'),
        _offer('2026-05-16', '2026-05-19', True),
    ]
    days = _by_day(gen.build_series(offers))
    assert days[date(2026, 5, 18)] == 2
    assert days[date(2026, 5, 17)] == 1


def test_outflow_counts_only_inactive_on_last_seen_day():
    offers = [
        _offer('2026-05-16', '2026-05-17'),           # znikła 17
        _offer('2026-05-16', '2026-05-17'),           # znikła 17
        _offer('2026-05-16', '2026-05-18'),           # znikła 18
        _offer('2026-05-16', '2026-05-18', True),     # aktywna → nie liczy się
    ]
    out = gen.build_outflow(offers)
    daily = _by_day(out['daily'])
    assert daily[date(2026, 5, 16)] == 0
    assert daily[date(2026, 5, 17)] == 2
    assert daily[date(2026, 5, 18)] == 1
    assert out['total'] == 3
    assert out['max_day'] == 2
    assert out['max_label'] == '17.05'
    assert out['rate'] == round(3 / 3, 1)             # 3 dni w oknie


def test_outflow_moving_average_is_trailing_7d():
    offers = (
        [_offer('2026-05-16', '2026-05-16')] * 7 +
        [_offer('2026-05-16', '2026-05-17', True)]
    )
    out = gen.build_outflow(offers)
    avg = _by_day(out['avg'])
    assert avg[date(2026, 5, 16)] == 7.0              # okno = 1 dzień
    assert avg[date(2026, 5, 17)] == 3.5              # (7+0)/2


def test_deltas_none_when_history_too_short():
    series = [[gen._day_ms(date(2026, 5, 16)) + i * gen.DAY_MS, 100 + i] for i in range(5)]
    deltas = gen.compute_deltas(series)
    assert deltas['1D'] == 1                          # 104 - 103
    assert deltas['1M'] is None                       # brak 30 dni historii
    assert deltas['6M'] is None and deltas['1Y'] is None


def test_deltas_1m_uses_value_30_days_back():
    series = [[gen._day_ms(date(2026, 5, 16)) + i * gen.DAY_MS, 100 + i] for i in range(40)]
    assert gen.compute_deltas(series)['1M'] == 30      # 139 - 109


def test_generate_writes_full_payload(tmp_path):
    offers = {'offers': [
        _offer('2026-05-16', '2026-05-17'),
        _offer('2026-05-16', '2026-05-19', True),
    ]}
    src = tmp_path / 'offers.json'
    dst = tmp_path / 'docs' / 'trend_data.json'
    src.write_text(json.dumps(offers), encoding='utf-8')

    assert gen.generate_trend_data(input_file=src, output_file=dst) is True

    data = json.loads(dst.read_text(encoding='utf-8'))
    assert data['title'] == gen.TITLE
    assert data['reliable_start'] == gen.RELIABLE_START.isoformat()
    assert data['points'] == len(data['series']) == 4  # 16–19.05
    assert data['current'] == 1 and data['max'] == 2 and data['min'] == 1
    assert data['last_label'] == '19.05.2026'
    assert data['outflow']['total'] == 1


def test_generate_returns_false_without_usable_offers(tmp_path):
    src = tmp_path / 'offers.json'
    dst = tmp_path / 'trend_data.json'
    src.write_text(json.dumps({'offers': []}), encoding='utf-8')

    assert gen.generate_trend_data(input_file=src, output_file=dst) is False
    assert not dst.exists()


def test_generate_raises_on_corrupted_input(tmp_path):
    src = tmp_path / 'offers.json'
    src.write_text('{ucięty', encoding='utf-8')
    with pytest.raises(json.JSONDecodeError):
        gen.generate_trend_data(input_file=src, output_file=tmp_path / 'out.json')

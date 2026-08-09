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


def _returned(first_seen, last_seen, days, active=True, gap_h=48.0, src='rescrape'):
    """Oferta z zapisanymi powrotami na rynek (`days` = lista dat ISO)."""
    offer = _offer(first_seen, last_seen, active)
    offer['reactivation_dates'] = [
        {'at': f'{d}T12:00:00+02:00', 'gap_h': gap_h, 'src': src} for d in days
    ]
    offer['reactivated_at'] = offer['reactivation_dates'][-1]['at']
    return offer


class TestInflow:
    def test_new_counts_offers_by_first_seen(self):
        offers = [
            _offer('2026-05-16', '2026-05-18'),
            _offer('2026-05-16', '2026-05-17'),
            _offer('2026-05-18', '2026-05-18', True),
        ]
        new = _by_day(gen.build_inflow(offers)['new']['daily'])
        assert new[date(2026, 5, 16)] == 2
        assert new[date(2026, 5, 17)] == 0
        assert new[date(2026, 5, 18)] == 1

    def test_react_masked_until_returns_are_measured(self):
        """Historia z nadpisywanego `reactivated_at` nie udaje pomiaru —
        seria jest pusta (None), a nie wyzerowana."""
        offers = [
            _offer('2026-05-16', '2026-05-20', True),
            {**_offer('2026-05-16', '2026-05-20'),
             'reactivated_at': '2026-05-18T12:00:00+02:00'},
        ]
        inflow = gen.build_inflow(offers)
        assert inflow['measured_from'] is None
        assert all(v is None for _, v in inflow['react']['daily'])
        assert inflow['react']['total'] == 0

    def test_react_starts_day_after_first_measurement(self):
        """Pierwszy dzień zapisu bywa urwany (skan rusza w środku dnia),
        więc oś zaczyna się od następnego."""
        offers = [
            _returned('2026-05-16', '2026-05-25', ['2026-05-20', '2026-05-22']),
            _returned('2026-05-16', '2026-05-25', ['2026-05-22']),
        ]
        inflow = gen.build_inflow(offers)
        daily = _by_day(inflow['react']['daily'])
        assert inflow['measured_from'] == '2026-05-21'
        assert daily[date(2026, 5, 20)] is None      # dzień startu zapisu
        assert daily[date(2026, 5, 21)] == 0
        assert daily[date(2026, 5, 22)] == 2
        assert inflow['react']['total'] == 2         # 20.05 nie wchodzi do sumy

    def test_react_skips_pipeline_artifact_day(self):
        day = sorted(gen.REACTIVATION_ARTIFACT_DAYS)[0].isoformat()
        offers = [
            _returned('2026-08-01', '2026-08-09', ['2026-08-02', day]),
            _returned('2026-08-01', '2026-08-09', [day]),
        ]
        daily = _by_day(gen.build_inflow(offers)['react']['daily'])
        assert daily[sorted(gen.REACTIVATION_ARTIFACT_DAYS)[0]] is None

    def test_new_react_is_the_sum_where_measured(self):
        offers = [
            _offer('2026-05-16', '2026-05-25', True),
            _returned('2026-05-16', '2026-05-25', ['2026-05-20', '2026-05-22']),
        ]
        inflow = gen.build_inflow(offers)
        both = _by_day(inflow['new_react']['daily'])
        new = _by_day(inflow['new']['daily'])
        react = _by_day(inflow['react']['daily'])
        assert both[date(2026, 5, 22)] == new[date(2026, 5, 22)] + react[date(2026, 5, 22)]
        assert both[date(2026, 5, 16)] is None       # przed pomiarem powrotów

    def test_moving_average_ignores_masked_days(self):
        offers = [_returned('2026-05-16', '2026-05-25',
                            ['2026-05-18', '2026-05-20', '2026-05-21'])]
        avg = _by_day(gen.build_inflow(offers)['react']['avg'])
        assert avg[date(2026, 5, 18)] is None        # dzień startu zapisu
        assert avg[date(2026, 5, 19)] == 0.0
        assert avg[date(2026, 5, 20)] == 0.5         # (0 + 1) / 2 dni

    def test_empty_input(self):
        assert gen.build_inflow([]) is None


class TestBands:
    def test_bands_sum_to_the_index(self):
        offers = [
            _offer('2026-05-16', '2026-05-25', True),
            _returned('2026-05-16', '2026-05-25', ['2026-05-18', '2026-05-20']),
            _offer('2026-05-19', '2026-05-22'),
        ]
        bands = gen.build_bands(offers)
        series = {ms: v for ms, v in gen.build_series(offers)}
        for (ms, fresh), (_, recycled) in zip(bands['new'], bands['react']):
            assert fresh + recycled == series[ms]

    def test_offer_moves_to_recycling_on_its_return_day(self):
        offers = [
            _returned('2026-05-16', '2026-05-25', ['2026-05-18']),   # ustawia start pomiaru
            _returned('2026-05-16', '2026-05-25', ['2026-05-21']),   # bohater testu
        ]
        bands = gen.build_bands(offers)
        fresh, recycled = _by_day(bands['new']), _by_day(bands['react'])
        assert fresh[date(2026, 5, 20)] == 1 and recycled[date(2026, 5, 20)] == 1
        assert fresh[date(2026, 5, 21)] == 0 and recycled[date(2026, 5, 21)] == 2
        assert recycled[date(2026, 5, 25)] == 2      # zostaje do końca życia

    def test_return_before_the_window_counts_from_its_first_day(self):
        """Oferta, która wróciła przed startem wykresu, jest recyklingiem
        od pierwszego dnia — nie „odmładza się" na krawędzi osi."""
        offers = [
            _returned('2026-05-16', '2026-05-25', ['2026-05-17']),
            _returned('2026-05-16', '2026-05-25', ['2026-05-20']),
        ]
        recycled = _by_day(gen.build_bands(offers)['react'])
        assert recycled[date(2026, 5, 18)] == 1

    def test_bands_start_where_measurement_starts(self):
        offers = [_returned('2026-05-16', '2026-05-25', ['2026-05-20', '2026-05-21'])]
        assert min(_by_day(gen.build_bands(offers)['new'])) == date(2026, 5, 21)

    def test_no_bands_without_measured_returns(self):
        assert gen.build_bands([_offer('2026-05-16', '2026-05-20', True)]) is None
        assert gen.build_bands([]) is None


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

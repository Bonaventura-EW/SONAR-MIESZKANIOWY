"""Testy rekonstrukcji indeksu podaży (trend_generator)."""

import json
import time
from datetime import date, timedelta

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


def test_outflow_counts_exits_from_the_index():
    """Odpływ = wyjścia z Indeksu, nie same dezaktywacje (FIX 2026-09-04).

    Oferta `active=True` z zestarzałym `last_seen` wypada z Indeksu od razu,
    a dezaktywacja przychodzi dopiero za kilka skanów. Gdy wykres na nią czekał,
    świeże dni dojrzewały jeszcze 2–3 doby wstecz (01.09: 6 → 40 → 43).
    """
    offers = [
        _offer('2026-05-16', '2026-05-17'),           # wyszła 17
        _offer('2026-05-16', '2026-05-17'),           # wyszła 17
        _offer('2026-05-16', '2026-05-18', True),     # active, ale stoi na 18
        _offer('2026-05-16', '2026-05-20', True),     # widziana do końca okna
    ]
    out = gen.build_outflow(offers)
    daily = _by_day(out['daily'])
    assert daily[date(2026, 5, 16)] == 0
    assert daily[date(2026, 5, 17)] == 2
    assert daily[date(2026, 5, 18)] == 1              # zestarzała aktywna też
    assert out['total'] == 3
    assert out['max_day'] == 2
    assert out['max_label'] == '17.05'


def test_outflow_stops_a_day_before_the_index():
    """Na ostatnim dniu okna koniec odcinka znaczy tylko „to nasza najświeższa
    obserwacja" — jeszcze nie wiadomo, czy oferta wyszła z rynku."""
    offers = [_offer('2026-05-16', '2026-05-20', True)]
    assert max(_by_day(gen.build_outflow(offers)['daily'])) == date(2026, 5, 19)
    assert max(_by_day(gen.build_series(offers))) == date(2026, 5, 20)


def test_outflow_counts_the_start_of_a_real_absence():
    """Oferta, która zniknęła i wróciła, wychodzi z Indeksu — a skoro powrót
    liczy się do napływu, to wyjście musi być w odpływie (symetria wykresów)."""
    offers = [_returned('2026-05-16', '2026-05-25', ['2026-05-21'])]
    daily = _by_day(gen.build_outflow(offers)['daily'])
    assert daily[date(2026, 5, 19)] == 1              # 20.05 oferty nie ma
    assert daily[date(2026, 5, 20)] == 0


def test_flows_reconcile_with_the_index():
    """Indeks(D) = Indeks(D−1) + napływ(D) − odpływ(D−1).

    Przed 2026-09-04 wykresy opisywały dwa różne rynki: za 12.08–03.09 napływ
    46,6/dzień wobec odpływu 40,3/dzień sugerował +146 ofert, podczas gdy
    Indeks urósł o 5.
    """
    offers = [
        _returned('2026-05-16', '2026-05-30', ['2026-05-18']),   # startuje pomiar
        _returned('2026-05-17', '2026-05-30', ['2026-05-24']),
        _offer('2026-05-16', '2026-05-22'),
        _offer('2026-05-20', '2026-05-26'),
        _offer('2026-05-16', '2026-05-30', True),
    ]
    series = _by_day(gen.build_series(offers))
    outflow = _by_day(gen.build_outflow(offers)['daily'])
    inflow = _by_day(gen.build_inflow(offers)['new_react']['daily'])
    checked = 0
    for day, value in sorted(series.items()):
        before = day - timedelta(days=1)
        if inflow.get(day) is None or outflow.get(before) is None:
            continue
        assert value == series[before] + inflow[day] - outflow[before], day
        checked += 1
    assert checked >= 8                               # test ma co sprawdzać


def test_outflow_skips_block_recovery_artifact_day():
    """Dzień blokada→odblokowanie (OUTFLOW_ARTIFACT_DAYS) to zrzut nagromadzonych
    dezaktywacji, nie realny odpływ — idzie do serii jako None i nie zawyża ani
    średniej, ani rekordu (inaczej „rekord 98" zamiast realnych ~50)."""
    art = sorted(gen.OUTFLOW_ARTIFACT_DAYS)[0]        # 2026-08-11
    art_iso = art.isoformat()
    offers = (
        [_offer('2026-05-16', '2026-08-04')] * 2 +    # realny odpływ 04.08
        [_offer('2026-05-16', art_iso)] * 50 +        # zrzut w dniu-artefakcie
        [_offer('2026-05-16', '2026-08-13', True)]    # aktywna → oś sięga za art
    )
    out = gen.build_outflow(offers)
    daily = _by_day(out['daily'])
    assert daily[art] is None                          # dzień-artefakt zamaskowany
    assert daily[date(2026, 8, 4)] == 2
    assert out['max_day'] == 2                          # rekord = realny dzień, nie 50
    assert out['total'] == 2                            # 50 z artefaktu poza sumą


def test_outflow_moving_average_is_trailing_7d():
    offers = (
        [_offer('2026-05-16', '2026-05-16')] * 7 +
        [_offer('2026-05-16', '2026-05-18', True)]    # aktywna → oś sięga 18
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
            _offer('2026-05-17', '2026-05-19'),
            _offer('2026-05-17', '2026-05-18'),
            _offer('2026-05-19', '2026-05-19', True),
        ]
        new = _by_day(gen.build_inflow(offers)['new']['daily'])
        assert new[date(2026, 5, 17)] == 2
        assert new[date(2026, 5, 18)] == 0
        assert new[date(2026, 5, 19)] == 1

    def test_new_skips_the_parser_backlog_day(self):
        """16.05 wróciło do bazy 97 ofert, które parser adresów odrzucał
        wcześniej — to zaległość pipeline'u, nie napływ z rynku, a stała jako
        rekord wykresu „Nowe oferty" (sąsiednie dni: 16–26)."""
        offers = ([_offer(gen.RELIABLE_START.isoformat(), '2026-05-20')] * 5
                  + [_offer('2026-05-17', '2026-05-20', True)])
        new = _by_day(gen.build_inflow(offers)['new']['daily'])
        assert new[gen.RELIABLE_START] is None
        assert new[date(2026, 5, 17)] == 1

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
        # Powroty 18. i 20.05 po 48 h → nieobecność 17. i 19.05. Trzeci powrót
        # 21.05 byłby sprzeczny (oferta nie może być naraz obecna 20.05
        # i nieobecna przez całą dobę przed 21.05).
        offers = [_returned('2026-05-16', '2026-05-25', ['2026-05-18', '2026-05-20'])]
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
        # 20.05 bohatera NIE MA na rynku: wrócił 21.05 po 48 h nieobecności,
        # więc dzień przed powrotem jest wycięty z okresu życia.
        assert fresh[date(2026, 5, 20)] == 0 and recycled[date(2026, 5, 20)] == 1
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


def _linear_series(start, count):
    """[[południe dnia, 100 + i], ...] — sztuczna, równo rosnąca seria."""
    return [[gen._day_ms(start + timedelta(days=i)), 100 + i] for i in range(count)]


def test_deltas_none_when_history_too_short():
    deltas = gen.compute_deltas(_linear_series(date(2026, 5, 16), 5))
    assert deltas['1D'] == 1                          # 104 - 103
    assert deltas['1M'] is None                       # brak 30 dni historii
    assert deltas['6M'] is None and deltas['1Y'] is None


def test_deltas_1m_uses_value_30_days_back():
    assert gen.compute_deltas(_linear_series(date(2026, 5, 16), 40))['1M'] == 30


@pytest.mark.skipif(not hasattr(time, 'tzset'), reason='tzset tylko na POSIX')
def test_deltas_survive_the_dst_change(monkeypatch):
    """Punkty stoją w POŁUDNIE czasu lokalnego, a doba zmiany czasu ma 23 h.

    Cel liczony jako `30 × 86_400_000 ms` lądował wtedy o 11:00 zamiast 12:00,
    więc `_value_at_or_before` brał dzień wcześniejszy i 1M mierzyło 31 dni.
    Okno 21.03 → 20.04.2027 przechodzi przez zmianę czasu 28.03.2027.
    """
    monkeypatch.setenv('TZ', 'Europe/Warsaw')
    time.tzset()
    try:
        series = _linear_series(date(2027, 2, 19), 61)   # ostatni punkt: 20.04.2027
        assert gen.compute_deltas(series)['1M'] == 30
    finally:
        monkeypatch.undo()
        time.tzset()


def test_rate_uses_the_recent_window_not_the_whole_history():
    """Średnia po całej historii mieszała trzy reżimy dezaktywacji i nie
    opisywała żadnego okresu: 26,1/dzień wobec ~43/dzień w ostatnim miesiącu."""
    days = [gen.RELIABLE_START + timedelta(days=i) for i in range(60)]
    counts = {day: (0 if i < 30 else 10) for i, day in enumerate(days)}
    metric = gen._flow_metric(counts, days)
    assert metric['rate_days'] == gen.FLOW_RATE_WINDOW_DAYS
    assert metric['rate'] == 10.0                     # ostatnie 30 dni
    assert metric['rate_all'] == 5.0                  # cała historia


class TestScanCoverage:
    """Doba z niepełną liczbą przebiegów widzi tylko wycinek listingu.

    Zmierzone 2026-09-04 na 18/19/31.08 (po 2 skany zamiast 3): Indeks leży
    średnio 17,5 oferty POD średnią sąsiednich dni, przy +7,1 dla dni pełnych —
    oferty urodzone i zmarłe w nieobserwowanym oknie dostają daty z sąsiada.
    """

    @staticmethod
    def _full(*days):
        return {day: gen.SCANS_PER_DAY for day in days}

    def test_partial_scan_day_is_a_gap(self):
        offers = [_offer('2026-05-16', '2026-05-20', True)]
        counts = self._full(*[date(2026, 5, d) for d in range(16, 21)])
        counts[date(2026, 5, 18)] = 1                 # skan padł po pierwszym przebiegu
        days = _by_day(gen.build_series(offers, counts))
        assert days[date(2026, 5, 18)] is None
        assert days[date(2026, 5, 19)] == 1

    def test_series_stops_at_the_last_complete_day(self):
        """Trwająca doba nie jest pokazywana jako zamknięta — to ona dawała
        „1D: −78" o poranku i „−8" wieczorem tego samego dnia."""
        offers = [_offer('2026-05-16', '2026-05-20', True)]
        counts = self._full(*[date(2026, 5, d) for d in range(16, 20)])
        counts[date(2026, 5, 20)] = 1                 # dziś, po pierwszym skanie
        assert max(_by_day(gen.build_series(offers, counts))) == date(2026, 5, 19)

    def test_first_day_of_the_log_is_never_partial(self):
        """Dziennik trzyma ostatnie ~100 przebiegów, więc najstarszy dzień bywa
        ucięty w połowie doby — nie robimy z niego luki."""
        offers = [_offer('2026-05-16', '2026-05-20', True)]
        counts = {date(2026, 5, 16): 1}
        counts.update(self._full(*[date(2026, 5, d) for d in range(17, 21)]))
        assert _by_day(gen.build_series(offers, counts))[date(2026, 5, 16)] == 1

    def test_partial_day_is_masked_in_every_metric(self):
        offers = [_returned('2026-05-16', '2026-05-25', ['2026-05-18'])]
        counts = self._full(*[date(2026, 5, d) for d in range(16, 26)])
        counts[date(2026, 5, 21)] = 1
        gap = date(2026, 5, 21)
        assert _by_day(gen.build_series(offers, counts))[gap] is None
        assert _by_day(gen.build_outflow(offers, counts)['daily'])[gap] is None
        assert _by_day(gen.build_inflow(offers, counts)['new']['daily'])[gap] is None
        bands = gen.build_bands(offers, counts)
        assert _by_day(bands['new'])[gap] is None
        assert _by_day(bands['react'])[gap] is None

    def test_a_plain_set_of_days_still_works(self):
        """Starsze wywołania podają sam zbiór dni — bez liczby przebiegów
        zakładamy pełne pokrycie, inaczej cała historia byłaby jedną luką."""
        offers = [_offer('2026-05-16', '2026-05-20', True)]
        days = _by_day(gen.build_series(offers,
                                        {date(2026, 5, d) for d in range(16, 21)}))
        assert list(days.values()) == [1] * 5


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


class TestSpansEndAtLastSeen:
    """Okres życia kończy się na `last_seen` — także dla ofert `active=True`.

    Regresja z 2026-09-02: aktywne oferty ciągnęły się do dnia ostatniego skanu,
    więc Indeks doliczał ogłoszenia, których scraper od tygodni nie widzi
    w listingu (1019 „aktywnych" wobec 774 realnie zebranych z OLX).
    """

    def test_stale_active_offer_stops_counting_after_last_seen(self):
        offers = [
            _offer('2026-05-16', '2026-05-25', True),        # widziana do końca
            _offer('2026-05-16', '2026-05-18', True),        # active, ale znikła 18.05
        ]
        days = _by_day(gen.build_series(offers))
        assert days[date(2026, 5, 18)] == 2
        assert days[date(2026, 5, 19)] == 1
        assert days[date(2026, 5, 25)] == 1

    def test_real_absence_is_cut_out_of_the_span(self):
        # Powrót 21.05 po 48 h nieobecności → 20.05 oferty nie było na rynku.
        offers = [_returned('2026-05-16', '2026-05-25', ['2026-05-21'])]
        days = _by_day(gen.build_series(offers))
        assert days[date(2026, 5, 19)] == 1
        assert days[date(2026, 5, 20)] == 0
        assert days[date(2026, 5, 21)] == 1

    def test_absence_is_cut_when_the_return_lands_earlier_in_the_day(self):
        """Skany chodzą 9:17/15:17/21:17, więc powrót bywa o pół doby wcześniej
        w dobie niż ostatnie widzenie. `int(gap_h // 24)` gubił wtedy całą dobę
        nieobecności (78 z 245 realnych powrotów w bazie) — oferta była naraz
        „wróciła na rynek" (napływ) i „ani na chwilę nie zniknęła" (Indeks)."""
        offer = _offer('2026-05-16', '2026-05-25', True)
        offer['reactivation_dates'] = [
            {'at': '2026-05-21T09:17:00+02:00', 'gap_h': 36.0, 'src': 'rescrape'}]
        days = _by_day(gen.build_series([offer]))
        assert days[date(2026, 5, 19)] == 1
        assert days[date(2026, 5, 20)] == 0           # 36 h przerwy = cały 20.05
        assert days[date(2026, 5, 21)] == 1

    def test_artifact_day_return_does_not_cut_the_index(self):
        """Powrót z dnia-artefaktu nie liczy się do napływu, więc i nieobecność
        nie może wyciąć dziury w Indeksie — inaczej wykresy przestają się
        domykać dokładnie w dniu, o którym wiemy, że jest zmyślony."""
        art = sorted(gen.REACTIVATION_ARTIFACT_DAYS)[0]     # 2026-08-05
        offer = _offer('2026-08-01', '2026-08-09', True)
        offer['reactivation_dates'] = [
            {'at': f'{art.isoformat()}T09:00:00+02:00', 'gap_h': 48.0, 'src': 'rescrape'}]
        days = _by_day(gen.build_series([offer]))
        assert days[art - timedelta(days=1)] == 1

    def test_verification_returns_are_not_absences(self):
        """`src='verification'` = nasza pomyłka przy dezaktywacji, nie zniknięcie
        oferty z OLX — dnia nie wycinamy (patrz reactivation_log.NOISE_SOURCES)."""
        offers = [_returned('2026-05-16', '2026-05-25', ['2026-05-21'], src='verification')]
        assert _by_day(gen.build_series(offers))[date(2026, 5, 20)] == 1

    def test_day_without_scan_is_a_gap_not_a_crash(self):
        offers = [_offer('2026-05-16', '2026-05-20', True)]
        scan_days = {date(2026, 5, 16), date(2026, 5, 17), date(2026, 5, 19), date(2026, 5, 20)}
        days = _by_day(gen.build_series(offers, scan_days))
        assert days[date(2026, 5, 18)] is None      # 18.05 skan nie chodził
        assert days[date(2026, 5, 19)] == 1
        # Luka nie może zatruć statystyk liczonych z serii.
        assert gen.compute_deltas(gen.build_series(offers, scan_days))['1D'] == 0

    def test_gaps_only_inside_the_scan_log_window(self):
        """Dni starsze niż dziennik skanów liczymy jak dotąd — o tym, czy skan
        wtedy chodził, dziennik po prostu nic nie wie."""
        offers = [_offer('2026-05-16', '2026-05-20', True)]
        days = _by_day(gen.build_series(offers, {date(2026, 5, 19), date(2026, 5, 20)}))
        assert days[date(2026, 5, 17)] == 1

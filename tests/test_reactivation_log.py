"""Testy zapisu historii powrotów ofert na rynek (reactivation_log).

Sedno: odróżnić powrót ogłoszenia od szumu pipeline'u. Scraper gubi oferty
z listingu na jeden skan, a weryfikacja „reaktywuje" ogłoszenia, które w ogóle
nie zniknęły z OLX — jedno i drugie musi wypaść z liczb, na których stoi
wykres reaktywacji.
"""

from datetime import date

import reactivation_log as log


def _at(day, hour=12):
    return f'2026-08-{day:02d}T{hour:02d}:00:00+02:00'


class TestRecord:
    def test_keeps_legacy_fields(self):
        offer = {'last_seen': _at(1)}
        log.record(offer, _at(5), 'rescrape', offer['last_seen'])
        assert offer['reactivated_at'] == _at(5)
        assert offer['reactivation_source'] == 'rescrape'

    def test_stores_gap_and_source(self):
        offer = {'last_seen': _at(1)}
        log.record(offer, _at(5), 'rescrape', offer['last_seen'])
        assert offer['reactivation_dates'] == [
            {'at': _at(5), 'src': 'rescrape', 'gap_h': 96.0}
        ]

    def test_missing_previous_last_seen_leaves_gap_unknown(self):
        offer = {}
        log.record(offer, _at(5), 'rescrape', None)
        assert 'gap_h' not in offer['reactivation_dates'][0]

    def test_naive_and_aware_dates_do_not_explode(self):
        offer = {'last_seen': '2026-08-01T12:00:00'}      # bez strefy
        log.record(offer, _at(5), 'rescrape', offer['last_seen'])
        assert 'gap_h' not in offer['reactivation_dates'][0]

    def test_same_day_returns_collapse_to_one_entry(self):
        offer = {'last_seen': _at(1)}
        log.record(offer, _at(5, 9), 'rescrape', offer['last_seen'])   # 93 h
        log.record(offer, _at(5, 21), 'rescrape', _at(5, 15))          # 6 h
        entries = offer['reactivation_dates']
        assert len(entries) == 1
        assert entries[0]['gap_h'] == 93.0        # zostaje najdłuższa przerwa

    def test_same_day_upgrades_noise_source_to_listing(self):
        offer = {'last_seen': _at(1)}
        log.record(offer, _at(5, 9), 'verification', offer['last_seen'])
        log.record(offer, _at(5, 21), 'rescrape', _at(5, 3))
        assert offer['reactivation_dates'][0]['src'] == 'rescrape'

    def test_does_not_merge_into_legacy_seed_from_the_same_day(self):
        """FIX 2026-08-10: zalążek przepisany z `reactivated_at` opisuje inny
        powrót i nie niesie pomiaru — scalenie z nim dawało rekord-hybrydę
        (czas jednego zdarzenia, gap drugiego, puste źródło)."""
        offer = {'reactivated_at': _at(10, 16), 'last_seen': _at(10, 16)}
        log.record(offer, _at(10, 21), 'verification', offer['last_seen'])
        seed, fresh = offer['reactivation_dates']
        assert seed == {'at': _at(10, 16)}            # zalążek nietknięty
        assert fresh['src'] == 'verification' and fresh['gap_h'] == 5.0

    def test_seeds_history_from_legacy_field(self):
        offer = {'reactivated_at': '2026-06-01T10:00:00+02:00'}
        log.record(offer, _at(5), 'rescrape', _at(1))
        assert [e['at'] for e in offer['reactivation_dates']] == [
            '2026-06-01T10:00:00+02:00', _at(5)
        ]

    def test_history_is_capped(self):
        offer = {}
        for day in range(1, 31):
            log.record(offer, f'2026-06-{day:02d}T12:00:00+02:00', 'rescrape', None)
        assert len(offer['reactivation_dates']) == 30
        log.MAX_ENTRIES, keep = 5, log.MAX_ENTRIES
        try:
            log.record(offer, _at(5), 'rescrape', None)
            assert len(offer['reactivation_dates']) == 5
            assert offer['reactivation_dates'][-1]['at'] == _at(5)
        finally:
            log.MAX_ENTRIES = keep


class TestReturnDays:
    def test_counts_return_after_real_absence(self):
        offer = {'last_seen': _at(1)}
        log.record(offer, _at(5), 'rescrape', offer['last_seen'])
        assert log.return_days(offer) == [date(2026, 8, 5)]

    def test_ignores_short_blink_of_the_listing(self):
        offer = {'last_seen': _at(5, 3)}
        log.record(offer, _at(5, 9), 'rescrape', offer['last_seen'])   # 6 h
        assert log.return_days(offer) == []

    def test_ignores_verification_even_after_long_gap(self):
        """Weryfikacja = oferta cały czas żyła na OLX, tylko wypadła z listingu."""
        offer = {'last_seen': _at(1)}
        log.record(offer, _at(6), 'verification', offer['last_seen'])
        assert log.return_days(offer) == []
        assert log.entries(offer)                 # surowy zapis zostaje

    def test_ignores_history_without_measured_gap(self):
        """Sprzed 08.2026 mamy jedną, nadpisywaną datę — nie da się z niej
        odtworzyć dnia po dniu, więc nie udajemy, że da się."""
        assert log.return_days({'reactivated_at': _at(3)}) == []
        assert log.measured_days({'reactivated_at': _at(3)}) == []

    def test_ignores_entry_with_unknown_source(self):
        """Bez źródła nie wiadomo, czy to powrót w listingu, czy nasza pomyłka
        przy dezaktywacji — więc nie jest to pomiar."""
        offer = {'reactivation_dates': [{'at': _at(5), 'gap_h': 96.0}]}
        assert log.return_days(offer) == []

    def test_skip_days_removes_artifact_day(self):
        offer = {'last_seen': _at(1)}
        log.record(offer, _at(5), 'rescrape', offer['last_seen'])
        assert log.return_days(offer, skip_days={date(2026, 8, 5)}) == []

    def test_first_return_day_is_the_earliest(self):
        offer = {'last_seen': _at(1)}
        log.record(offer, _at(5), 'rescrape', offer['last_seen'])
        log.record(offer, _at(9), 'rescrape', _at(7))
        assert log.first_return_day(offer) == date(2026, 8, 5)
        assert log.first_return_day({}) is None


class TestEntries:
    def test_tolerates_plain_iso_strings(self):
        offer = {'reactivation_dates': ['2026-08-05T12:00:00+02:00']}
        assert log.entries(offer) == [{'at': '2026-08-05T12:00:00+02:00'}]

    def test_ignores_garbage(self):
        offer = {'reactivation_dates': [None, {}, {'at': _at(5)}]}
        assert log.entries(offer) == [{'at': _at(5)}]

    def test_broken_date_does_not_break_return_days(self):
        offer = {'reactivation_dates': [{'at': 'wczoraj', 'gap_h': 50, 'src': 'rescrape'}]}
        assert log.return_days(offer) == []

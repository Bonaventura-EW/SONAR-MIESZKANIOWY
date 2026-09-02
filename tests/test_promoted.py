"""Testy metryki ofert PROMOWANYCH (płatne wyróżnienia na listingu OLX).

Pokrywa trzy warstwy propagacji z SONAR-POKOJOWY, zaadaptowane do naszego kodu:
  - scraper: detekcja z parametru atrybucji `search_reason` + fallback plakietki,
    dedup podnoszący flagę (ten sam kafelek promowany i organiczny na jednej stronie),
  - main: `_track_promoted` (max 1 dzień/wpis) i backfill z zapisanego URL-a,
  - trend_generator: `build_promoted` (dzienny szereg + udział w rynku).
"""

import json
from datetime import date, datetime

import pytest
import pytz
from bs4 import BeautifulSoup

import trend_generator as gen
from scraper import OLXScraper
from main import SonarMieszkaniowy

TZ = pytz.timezone('Europe/Warsaw')
BASE = 'https://www.olx.pl/d/oferta/mieszkanie-CID3-ID{}.html'


# ── scraper: detekcja wyróżnienia ────────────────────────────────────────────

class TestIsPromotedHref:
    def test_promoted_attribution(self):
        assert OLXScraper._is_promoted_href(
            BASE.format(1) + '?reason=extended_search&search_reason=search%7Cpromoted')

    def test_organic_attribution(self):
        assert not OLXScraper._is_promoted_href(
            BASE.format(1) + '?search_reason=search%7Corganic')

    def test_no_query_string(self):
        assert not OLXScraper._is_promoted_href(BASE.format(1))

    def test_empty_or_none(self):
        assert not OLXScraper._is_promoted_href('')
        assert not OLXScraper._is_promoted_href(None)

    def test_decoded_pipe_also_matches(self):
        assert OLXScraper._is_promoted_href(BASE.format(1) + '?search_reason=search|promoted')


def _card_html(offer_id, query='', badge=False):
    href = BASE.format(offer_id) + query
    badge_tag = '<span data-testid="adCard-featured">Wyróżnione</span>' if badge else ''
    return (
        f'<div class="card">'
        f'  <div><a href="{href}">link</a></div>'
        f'  {badge_tag}'
        f'  <h6>Ładne mieszkanie {offer_id}</h6>'
        f'  <p data-testid="ad-price">2000 zł</p>'
        f'</div>'
    )


def _scraper():
    return OLXScraper(delay_range=(0, 0), max_workers=1)


class TestExtractPromoted:
    def test_flag_set_from_href(self):
        html = _card_html(1, '?search_reason=search%7Cpromoted')
        offers = _scraper()._extract_offers_from_page(BeautifulSoup(html, 'lxml'))
        assert len(offers) == 1 and offers[0]['promoted'] is True

    def test_organic_not_promoted(self):
        html = _card_html(1, '?search_reason=search%7Corganic')
        offers = _scraper()._extract_offers_from_page(BeautifulSoup(html, 'lxml'))
        assert offers[0]['promoted'] is False

    def test_badge_fallback_when_no_attribution(self):
        html = _card_html(1, query='', badge=True)
        offers = _scraper()._extract_offers_from_page(BeautifulSoup(html, 'lxml'))
        assert offers[0]['promoted'] is True

    def test_dedup_raises_flag_when_second_occurrence_promoted(self):
        """Ten sam kafelek dwa razy na stronie (organiczny + promowany blok NAD
        listingiem) — dedup musi PODNIEŚĆ flagę, nie wziąć pierwszego trafienia."""
        html = (_card_html(7, '?search_reason=search%7Corganic')
                + _card_html(7, '?search_reason=search%7Cpromoted'))
        offers = _scraper()._extract_offers_from_page(BeautifulSoup(html, 'lxml'))
        assert len(offers) == 1 and offers[0]['promoted'] is True

    def test_attribution_missing_alarm_counter(self):
        """Gdy żaden kafelek nie niesie search_reason, `attributed` = 0 (alarm)."""
        sc = _scraper()
        sc._extract_offers_from_page(BeautifulSoup(_card_html(1), 'lxml'))
        assert sc.promoted_stats['cards'] == 1 and sc.promoted_stats['attributed'] == 0


# ── main: śledzenie i backfill ───────────────────────────────────────────────

@pytest.fixture
def agent(tmp_path):
    db = {'last_scan': None, 'next_scan': None, 'offers': []}
    data_file = tmp_path / 'offers.json'
    data_file.write_text(json.dumps(db), encoding='utf-8')
    return SonarMieszkaniowy(
        data_file=str(data_file),
        removed_file=str(tmp_path / 'removed.json'),
    )


class TestTrackPromoted:
    def test_adds_today_once(self, agent):
        offer = {}
        assert agent._track_promoted(offer, True) is True
        assert agent._track_promoted(offer, True) is False       # ten sam dzień
        today = datetime.now(TZ).strftime('%Y-%m-%d')
        assert offer['promoted_dates'] == [today]
        assert offer['promoted'] is True and offer['promoted_count'] == 1

    def test_not_promoted_clears_flag_keeps_history(self, agent):
        offer = {'promoted': True, 'promoted_dates': ['2026-08-30'], 'promoted_count': 1}
        assert agent._track_promoted(offer, False) is False
        assert offer['promoted'] is False
        assert offer['promoted_dates'] == ['2026-08-30']         # historia nietknięta


class TestBackfillPromotedFromUrl:
    def test_active_promoted_seeded_with_today(self, agent):
        agent.database['offers'] = [
            {'active': True, 'url': BASE.format(1) + '?search_reason=search%7Cpromoted'},
            {'active': True, 'url': BASE.format(2) + '?search_reason=search%7Corganic'},
            {'active': False, 'url': BASE.format(3) + '?search_reason=search%7Cpromoted'},
        ]
        agent._backfill_promoted_from_url()
        today = datetime.now(TZ).strftime('%Y-%m-%d')
        o1, o2, o3 = agent.database['offers']
        assert o1['promoted'] is True and o1['promoted_dates'] == [today]
        assert o2['promoted'] is False and o2['promoted_dates'] == []
        assert o3['promoted'] is False and o3['promoted_dates'] == []   # nieaktywna → nie seedujemy

    def test_idempotent_skips_offers_with_flag(self, agent):
        agent.database['offers'] = [
            {'active': True, 'promoted': True, 'promoted_dates': ['2026-08-30'],
             'url': BASE.format(1) + '?search_reason=search%7Corganic'},
        ]
        agent._backfill_promoted_from_url()
        assert agent.database['offers'][0]['promoted_dates'] == ['2026-08-30']


# ── trend_generator: dzienny szereg ──────────────────────────────────────────

def _offer(first_seen, last_seen, active=False, promoted_dates=None):
    o = {
        'first_seen': f'{first_seen}T10:00:00+02:00',
        'last_seen': f'{last_seen}T18:00:00+02:00',
        'active': active,
    }
    if promoted_dates is not None:
        o['promoted_dates'] = promoted_dates
    return o


def _by_day(series):
    return {datetime.fromtimestamp(ms / 1000).date(): val for ms, val in series}


class TestBuildPromoted:
    def test_none_without_any_promoted_dates(self):
        offers = [_offer('2026-05-16', '2026-05-20', True)]
        assert gen.build_promoted(offers, gen.build_series(offers)) is None

    def test_daily_counts_and_share(self):
        offers = [
            _offer('2026-08-30', '2026-09-01', True, ['2026-08-31', '2026-09-01']),
            _offer('2026-08-30', '2026-09-01', True, ['2026-09-01']),
            _offer('2026-08-30', '2026-09-01', True),                     # nigdy promowana
        ]
        series = gen.build_series(offers)
        pr = gen.build_promoted(offers, series)
        daily = _by_day(pr['daily'])
        assert daily[date(2026, 8, 31)] == 1
        assert daily[date(2026, 9, 1)] == 2
        assert pr['current'] == 2
        # udział = promowane / aktywne (3 żywe oferty tego dnia)
        assert pr['current_share'] == round(100 * 2 / 3, 1)
        assert pr['start'] == '2026-08-31'
        assert 'total' not in pr                                          # metryka STANU

    def test_history_starts_at_first_promoted_day_not_reliable_start(self):
        offers = [_offer('2026-05-16', '2026-09-01', True, ['2026-09-01'])]
        pr = gen.build_promoted(offers, gen.build_series(offers))
        assert pr['start'] == '2026-09-01'                               # nie RELIABLE_START

    def test_load_scan_days_reads_completed_scans(self, tmp_path):
        (tmp_path / 'scan_history.json').write_text(json.dumps([
            {'timestamp': '2026-09-01T09:17:00+02:00', 'status': 'completed'},
            {'timestamp': '2026-09-01T15:17:00+02:00', 'status': 'error'},
            {'timestamp': '2026-08-31T21:17:00+02:00', 'status': 'warning'},
        ]), encoding='utf-8')
        days = gen.load_scan_days(tmp_path / 'offers.json')
        assert days == {date(2026, 9, 1), date(2026, 8, 31)}             # error pominięty

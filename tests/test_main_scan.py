"""Testy logiki skanu w main.py (bez sieci i bez realnych plików repo)."""

import json
from datetime import datetime, timedelta

import pytest
import pytz
import requests

from main import SonarMieszkaniowy

TZ = pytz.timezone('Europe/Warsaw')


def _offer(oid, active=False, last_seen=None, **extra):
    last_seen = last_seen or datetime.now(TZ).isoformat()
    base = {
        'id': f'oferta-{oid}-CID3-ID{oid}',
        'url': f'https://www.olx.pl/d/oferta/oferta-{oid}-CID3-ID{oid}.html',
        'active': active,
        'first_seen': last_seen,
        'last_seen': last_seen,
        'price': {'current': 2000, 'history': [2000]},
        'description': f'opis {oid}',
        'address': {'full': f'Testowa {oid}'},
    }
    base.update(extra)
    return base


@pytest.fixture
def agent(tmp_path):
    db = {'last_scan': None, 'next_scan': None, 'offers': []}
    data_file = tmp_path / 'offers.json'
    data_file.write_text(json.dumps(db), encoding='utf-8')
    return SonarMieszkaniowy(
        data_file=str(data_file),
        removed_file=str(tmp_path / 'removed.json'),
    )


class TestDeactivationProtection:
    """Najważniejszy bezpiecznik systemu: przy blokadzie OLX (0 ofert lub <30%
    aktywnych) NIE dezaktywujemy ofert. CLAUDE.md: 'Nie usuwaj tej ochrony'."""

    def test_zero_offers_blocks_deactivation(self, agent):
        assert agent._deactivation_block_reason(0, 500) is not None

    def test_below_30pct_ratio_blocks_deactivation(self, agent):
        assert agent._deactivation_block_reason(100, 500) is not None  # próg: 150

    def test_healthy_scan_allows_deactivation(self, agent):
        assert agent._deactivation_block_reason(200, 500) is None

    def test_empty_database_first_run_allows(self, agent):
        assert agent._deactivation_block_reason(0, 0) is None

    def test_small_database_exempt_from_ratio(self, agent):
        # Baza <10 aktywnych: próg procentowy nie obowiązuje (ale 0 ofert blokuje)
        assert agent._deactivation_block_reason(2, 9) is None
        assert agent._deactivation_block_reason(0, 9) is not None

    def test_mark_inactive_offers_deactivates_missing(self, agent):
        agent.database['offers'] = [
            _offer('aaa1', active=True),
            _offer('bbb2', active=True),
        ]
        deactivated = agent._mark_inactive_offers(
            current_offer_ids=['oferta-aaa1-CID3-IDaaa1'], skipped_offer_ids=[]
        )
        assert deactivated == 1
        by_cid = {o['id']: o for o in agent.database['offers']}
        assert by_cid['oferta-aaa1-CID3-IDaaa1']['active'] is True
        assert by_cid['oferta-bbb2-CID3-IDbbb2']['active'] is False

    def test_mark_inactive_reactivates_skipped(self, agent):
        agent.database['offers'] = [_offer('ccc3', active=False)]
        agent._mark_inactive_offers(
            current_offer_ids=[], skipped_offer_ids=['oferta-ccc3-CID3-IDccc3']
        )
        offer = agent.database['offers'][0]
        assert offer['active'] is True
        assert offer['reactivation_source'] == 'skipped'


class TestPriceUpdateLogic:
    """FIX 2026-06-12: upgrade źródła z różnicą >=50% = korekta błędu parsera,
    nie rynkowa zmiana ceny (bez trend/previous_price/price_changes/top5)."""

    def _existing(self, price=800, source='Parser tekstowy'):
        return {
            'id': 'x-CID3-IDabc', 'url': 'https://olx.pl/d/oferta/x-CID3-IDabc.html',
            'active': True,
            'price': {'current': price, 'history': [price], 'source': source,
                      'media_info': 'brak informacji'},
            'address': {'full': 'Testowa 1', 'has_number': True},
        }

    def _new(self, price, source='JSON-LD (OLX)'):
        return {
            'id': 'x-CID3-IDabc', 'url': 'https://olx.pl/d/oferta/x-CID3-IDabc.html',
            'price': {'current': price, 'history': [price], 'source': source,
                      'media_info': 'brak informacji'},
            'address': {'full': 'Testowa 1', 'has_number': True},
        }

    def test_source_upgrade_with_huge_diff_is_silent_correction(self, agent):
        existing = self._existing(price=800, source='Parser tekstowy')
        agent._update_existing_offer(existing, self._new(price=2400))
        assert existing['price']['current'] == 2400          # cena poprawiona
        assert existing['price']['source'] == 'JSON-LD (OLX)'
        assert 'price_trend' not in existing['price']        # bez "zmiany ceny"
        assert 'previous_price' not in existing['price']
        assert 'price_changes' not in existing['price']
        assert existing['price']['history'] == [2400]        # nadpisany błędny wpis

    def test_source_upgrade_with_small_diff_is_real_change(self, agent):
        existing = self._existing(price=2000, source='Parser tekstowy')
        agent._update_existing_offer(existing, self._new(price=1900))
        assert existing['price']['current'] == 1900
        assert existing['price']['price_trend'] == 'down'
        assert existing['price']['previous_price'] == 2000
        assert len(existing['price']['price_changes']) == 1

    def test_same_source_huge_diff_still_ignored(self, agent):
        existing = self._existing(price=2000, source='JSON-LD (OLX)')
        agent._update_existing_offer(existing, self._new(price=9000))
        assert existing['price']['current'] == 2000  # podejrzana zmiana — ignorowana


class TestVerifyCooldown:
    """FIX 2026-06-12: oferty potwierdzone jako nieaktywne nie są
    re-weryfikowane przez 7 dni (wcześniej te same 50 co skan, 3×dziennie)."""

    def test_recently_verified_offers_are_skipped(self, agent, monkeypatch):
        now = datetime.now(TZ)
        fresh = (now - timedelta(days=1)).isoformat()
        stale = (now - timedelta(days=30)).isoformat()
        agent.database['offers'] = [
            _offer('aaa1', verified_inactive_at=fresh),   # świeżo potwierdzona → pomiń
            _offer('bbb2', verified_inactive_at=stale),   # stary znacznik → sprawdź
            _offer('ccc3'),                               # bez znacznika → sprawdź
        ]

        attempted = []

        def fake_get(self, url, **kw):
            attempted.append(url)
            raise requests.RequestException('sieć zablokowana w teście')

        monkeypatch.setattr(requests.Session, 'get', fake_get)
        stats = agent._verify_inactive_offers(max_to_verify=50)

        assert stats['skipped_recently_verified'] == 1
        assert len(attempted) == 2
        assert stats['errors'] == 2

    def test_confirmed_inactive_gets_marker(self, agent, monkeypatch):
        agent.database['offers'] = [_offer('ddd4')]

        class FakeResp:
            status_code = 404
            text = ''

        monkeypatch.setattr(requests.Session, 'get', lambda self, url, **kw: FakeResp())
        stats = agent._verify_inactive_offers(max_to_verify=50)

        assert stats['confirmed_inactive'] == 1
        assert agent.database['offers'][0].get('verified_inactive_at')

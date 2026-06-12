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

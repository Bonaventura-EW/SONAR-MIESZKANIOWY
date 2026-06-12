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

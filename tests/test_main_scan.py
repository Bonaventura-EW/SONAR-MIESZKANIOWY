"""Testy logiki skanu w main.py (bez sieci i bez realnych plików repo)."""

import json
from datetime import datetime, timedelta

import pytest
import pytz
import requests

import http_client
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
    """Najważniejszy bezpiecznik systemu: przy blokadzie OLX (0 ofert lub <60%
    aktywnych) NIE dezaktywujemy ofert. CLAUDE.md: 'Nie usuwaj tej ochrony'."""

    def test_zero_offers_blocks_deactivation(self, agent):
        assert agent._deactivation_block_reason(0, 500) is not None

    def test_far_below_ratio_blocks_deactivation(self, agent):
        assert agent._deactivation_block_reason(100, 500) is not None  # próg: 300

    def test_partial_block_below_60pct_blocks_deactivation(self, agent):
        # FIX 2026-08-05: częściowa blokada (realny incydent 2026-08-05 06:31 —
        # 365 ofert przy 706 aktywnych, ratio 0.52) wcześniej prześlizgiwała się
        # pod progiem 0.3 i dezaktywowała 409 realnych ofert. Próg 0.6 ją łapie.
        assert agent._deactivation_block_reason(365, 706) is not None  # próg: 423

    def test_healthy_scan_allows_deactivation(self, agent):
        # Zdrowy skan zwraca ofert więcej niż aktywnych w bazie (ratio ~1.08).
        assert agent._deactivation_block_reason(520, 500) is None

    def test_empty_database_first_run_allows(self, agent):
        assert agent._deactivation_block_reason(0, 0) is None

    def test_small_database_exempt_from_ratio(self, agent):
        # Baza <10 aktywnych: próg procentowy nie obowiązuje (ale 0 ofert blokuje)
        assert agent._deactivation_block_reason(2, 9) is None
        assert agent._deactivation_block_reason(0, 9) is not None

    def test_single_miss_does_not_deactivate(self, agent):
        # FIX 2026-08-12: jedno zniknięcie z listingu = szum paginacji, nie
        # dezaktywacja. Oferta zostaje aktywna z licznikiem chybień = 1.
        agent.database['offers'] = [
            _offer('aaa1', active=True),
            _offer('bbb2', active=True),
        ]
        candidates = agent._reconcile_presence(
            current_offer_ids=['oferta-aaa1-CID3-IDaaa1'], skipped_offer_ids=[]
        )
        by_cid = {o['id']: o for o in agent.database['offers']}
        assert by_cid['oferta-bbb2-CID3-IDbbb2']['active'] is True      # NIE zdezaktywowana
        assert by_cid['oferta-bbb2-CID3-IDbbb2']['missing_streak'] == 1
        assert candidates == []                                         # jeszcze nie kandydat
        assert 'missing_streak' not in by_cid['oferta-aaa1-CID3-IDaaa1']  # obecna → brak licznika

    def test_two_misses_becomes_candidate_still_active(self, agent):
        # Po progu (2 chybienia) oferta staje się KANDYDATEM, ale wciąż aktywna —
        # o dezaktywacji decyduje dopiero _verify_and_deactivate (link).
        agent.database['offers'] = [_offer('bbb2', active=True)]
        agent._reconcile_presence(current_offer_ids=[], skipped_offer_ids=[])   # miss 1
        candidates = agent._reconcile_presence(current_offer_ids=[], skipped_offer_ids=[])  # miss 2
        offer = agent.database['offers'][0]
        assert offer['missing_streak'] == 2
        assert offer['active'] is True                 # wciąż aktywna
        assert candidates == [offer]                   # ale już kandydat do sprawdzenia linku

    def test_presence_resets_missing_streak(self, agent):
        agent.database['offers'] = [_offer('bbb2', active=True)]
        agent._reconcile_presence(current_offer_ids=[], skipped_offer_ids=[])   # miss 1
        assert agent.database['offers'][0]['missing_streak'] == 1
        agent._reconcile_presence(current_offer_ids=['oferta-bbb2-CID3-IDbbb2'], skipped_offer_ids=[])
        assert 'missing_streak' not in agent.database['offers'][0]              # obecność zeruje

    def test_reconcile_reactivates_skipped(self, agent):
        agent.database['offers'] = [_offer('ccc3', active=False)]
        agent._reconcile_presence(
            current_offer_ids=[], skipped_offer_ids=['oferta-ccc3-CID3-IDccc3']
        )
        offer = agent.database['offers'][0]
        assert offer['active'] is True
        assert offer['reactivation_source'] == 'skipped'

    def test_reactivation_lands_in_history_with_gap(self, agent):
        """FIX 2026-08-09: sam `reactivated_at` jest nadpisywany, więc każdy
        powrót dopisujemy osobno — z długością nieobecności, bo bez niej nie da
        się odróżnić powrotu na rynek od zgubienia oferty na jeden skan."""
        gone_since = (datetime.now(TZ) - timedelta(days=3)).isoformat()
        agent.database['offers'] = [_offer('ddd4', active=False, last_seen=gone_since)]
        agent._reconcile_presence(
            current_offer_ids=[], skipped_offer_ids=['oferta-ddd4-CID3-IDddd4']
        )
        history = agent.database['offers'][0]['reactivation_dates']
        assert len(history) == 1
        assert history[0]['src'] == 'skipped'
        assert 71 <= history[0]['gap_h'] <= 73          # ~3 doby nieobecności

    def test_reactivation_from_listing_records_gap(self, agent):
        """Ta sama historia dla powrotu w listingu (`_update_existing_offer`):
        gap liczy się od last_seen SPRZED aktualizacji, nie od „teraz"."""
        gone_since = (datetime.now(TZ) - timedelta(days=2)).isoformat()
        existing = _offer('eee5', active=False, last_seen=gone_since)
        scraped = _offer('eee5', active=True)
        scraped['price'] = {'current': 2000, 'history': [2000], 'media_info': None}
        agent._update_existing_offer(existing, scraped)
        history = existing['reactivation_dates']
        assert existing['active'] is True
        assert history[-1]['src'] == 'rescrape'
        assert 47 <= history[-1]['gap_h'] <= 49


class TestRetryOnBlock:
    """FIX 2026-08-05: przy wykrytej blokadzie OLX (run_scan zwraca True)
    run_scan_with_retry czeka i ponawia skan, aż do RETRY_ON_BLOCK_MAX_RETRIES
    dodatkowych prób. Bez blokady (False) — żadnego retry ani czekania."""

    def _patch(self, agent, monkeypatch, results):
        """Podmienia run_scan sekwencją wyników i wyłapuje sleepy (bez czekania)."""
        calls = {'scan': 0}
        sleeps = []

        def fake_run_scan():
            i = calls['scan']
            calls['scan'] += 1
            # Po wyczerpaniu sekwencji trzymaj ostatni wynik (blokada trwa).
            return results[i] if i < len(results) else results[-1]

        monkeypatch.setattr(agent, 'run_scan', fake_run_scan)
        monkeypatch.setattr('main.time.sleep', lambda s: sleeps.append(s))
        return calls, sleeps

    def test_healthy_scan_runs_once_without_sleep(self, agent, monkeypatch):
        calls, sleeps = self._patch(agent, monkeypatch, [False])
        blocked = agent.run_scan_with_retry()
        assert blocked is False
        assert calls['scan'] == 1
        assert sleeps == []

    def test_block_then_recovery_retries_and_succeeds(self, agent, monkeypatch):
        calls, sleeps = self._patch(agent, monkeypatch, [True, False])
        blocked = agent.run_scan_with_retry(wait_seconds=120, max_retries=2)
        assert blocked is False
        assert calls['scan'] == 2          # blokada + udany retry
        assert sleeps == [120]             # jedno czekanie 2 min

    def test_persistent_block_stops_after_max_retries(self, agent, monkeypatch):
        calls, sleeps = self._patch(agent, monkeypatch, [True])  # zawsze blokada
        blocked = agent.run_scan_with_retry(wait_seconds=120, max_retries=2)
        assert blocked is True
        assert calls['scan'] == 3          # 1 początkowa + 2 retry
        assert sleeps == [120, 120]        # dwa czekania, potem koniec

    def test_no_retries_config_runs_once(self, agent, monkeypatch):
        calls, sleeps = self._patch(agent, monkeypatch, [True])
        blocked = agent.run_scan_with_retry(wait_seconds=120, max_retries=0)
        assert blocked is True
        assert calls['scan'] == 1
        assert sleeps == []


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


class _Resp:
    """Uproszczona odpowiedź HTTP do podmiany ImpersonatedSession.get."""
    def __init__(self, status_code, text=''):
        self.status_code = status_code
        self.text = text


_ALIVE_HTML = ('<html><body><script type="application/ld+json">'
               '{"@type":"Product","offers":{"availability":"https://schema.org/InStock"}}'
               '</script></body></html>')
_DEAD_HTML = '<html><body><h1>Ogłoszenie zakończone</h1></body></html>'


class TestVerifyAndDeactivate:
    """FIX 2026-08-12: dezaktywacja na podstawie REALNEGO stanu oferty (link),
    nie nieobecności w listingu. 404/nie-InStock → dezaktywuj; 200+InStock →
    zostaw; 403/błąd → zostaw (błąd ≠ śmierć oferty). Circuit breaker chroni
    przed biciem w zdławione IP."""

    def _patch_get(self, monkeypatch, resp_or_fn):
        fn = resp_or_fn if callable(resp_or_fn) else (lambda self, url, **kw: resp_or_fn)
        monkeypatch.setattr(http_client.ImpersonatedSession, 'get', fn)
        monkeypatch.setattr('main.time.sleep', lambda s: None)   # bez czekania w teście

    def test_dead_link_404_deactivates(self, agent, monkeypatch):
        offer = _offer('aaa1', active=True, missing_streak=2)
        self._patch_get(monkeypatch, lambda self, url, **kw: _Resp(404))
        stats = agent._verify_and_deactivate([offer])
        assert stats['confirmed_inactive'] == 1
        assert offer['active'] is False
        assert offer.get('verified_inactive_at')
        assert 'missing_streak' not in offer

    def test_dead_page_200_without_instock_deactivates(self, agent, monkeypatch):
        offer = _offer('aaa2', active=True, missing_streak=2)
        self._patch_get(monkeypatch, lambda self, url, **kw: _Resp(200, _DEAD_HTML))
        stats = agent._verify_and_deactivate([offer])
        assert stats['confirmed_inactive'] == 1
        assert offer['active'] is False

    def test_alive_link_keeps_active_and_resets_streak(self, agent, monkeypatch):
        offer = _offer('bbb2', active=True, missing_streak=2)
        self._patch_get(monkeypatch, lambda self, url, **kw: _Resp(200, _ALIVE_HTML))
        stats = agent._verify_and_deactivate([offer])
        assert stats['still_alive'] == 1
        assert stats['confirmed_inactive'] == 0
        assert offer['active'] is True
        assert 'missing_streak' not in offer          # link żyje → reset licznika

    def test_error_403_keeps_active(self, agent, monkeypatch):
        offer = _offer('ccc3', active=True, missing_streak=2)
        self._patch_get(monkeypatch, lambda self, url, **kw: _Resp(403))
        stats = agent._verify_and_deactivate([offer])
        assert stats['errors'] == 1
        assert stats['confirmed_inactive'] == 0
        assert offer['active'] is True                # 403 ≠ dezaktywacja

    def test_network_error_keeps_active(self, agent, monkeypatch):
        offer = _offer('ddd4', active=True, missing_streak=2)
        def boom(self, url, **kw):
            raise requests.RequestException('sieć w teście')
        self._patch_get(monkeypatch, boom)
        stats = agent._verify_and_deactivate([offer])
        assert stats['errors'] == 1
        assert offer['active'] is True

    def test_circuit_breaker_stops_after_consecutive_errors(self, agent, monkeypatch):
        offers = [_offer(f'o{i}', active=True, missing_streak=2) for i in range(20)]
        self._patch_get(monkeypatch, lambda self, url, **kw: _Resp(403))
        stats = agent._verify_and_deactivate(offers)
        assert stats['circuit_broken'] is True
        assert stats['errors'] == agent.LINK_CHECK_ERROR_CIRCUIT   # przerwane na progu
        assert all(o['active'] for o in offers)                    # nic nie zdezaktywowane

    def test_empty_candidates_no_requests(self, agent, monkeypatch):
        called = []
        self._patch_get(monkeypatch, lambda self, url, **kw: called.append(url) or _Resp(200))
        stats = agent._verify_and_deactivate([])
        assert stats == {'checked': 0, 'confirmed_inactive': 0, 'still_alive': 0,
                         'errors': 0, 'circuit_broken': False, 'candidates': 0}
        assert called == []

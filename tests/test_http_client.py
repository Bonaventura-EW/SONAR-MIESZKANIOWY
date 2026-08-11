"""Testy http_client: impersonacja TLS z fallbackiem na requests.

Nie dotykają sieci — sprawdzają samą logikę wyboru backendu, nagłówki,
per-wątkowość sesji i fallback transportowy.
"""

import threading

import requests

import http_client
from http_client import ImpersonatedSession


def test_request_error_covers_requests_exceptions():
    # Kod woła `except http_client.RequestError` — musi łapać wyjątki requests.
    assert requests.RequestException in http_client.RequestError


def test_headers_applied_to_underlying_session():
    headers = {'User-Agent': 'test-agent', 'Accept-Language': 'pl'}
    sess = ImpersonatedSession(headers=headers)
    # Sesja per-wątek jest tworzona leniwie; fabryka nakłada nasze nagłówki.
    underlying = sess._new_requests_session()
    assert underlying.headers.get('User-Agent') == 'test-agent'
    assert underlying.headers.get('Accept-Language') == 'pl'


def test_get_uses_requests_when_curl_unavailable(monkeypatch):
    sentinel = object()

    class FakeReqSession:
        def get(self, url, **kw):
            return sentinel

    monkeypatch.setattr(http_client, 'CURL_CFFI_AVAILABLE', False)
    sess = ImpersonatedSession(headers={})
    monkeypatch.setattr(sess, '_new_requests_session', lambda: FakeReqSession())
    assert sess.get('https://example.test') is sentinel


def test_get_falls_back_to_requests_on_transport_error(monkeypatch):
    # Gdy impersonowany handshake padnie na poziomie transportu, get() ma dokończyć
    # zwykłym requests — bez tego pojedynczy błąd TLS wywaliłby cały skan.
    if not http_client.CURL_CFFI_AVAILABLE:
        import pytest
        pytest.skip('curl_cffi niedostępny — brak ścieżki fallbacku do przetestowania')

    sentinel = object()
    curl_exc = http_client._CurlRequestException('reset przez peer')

    class BoomCurl:
        def get(self, url, **kw):
            raise curl_exc

    class FakeReqSession:
        def get(self, url, **kw):
            return sentinel

    sess = ImpersonatedSession(headers={})
    monkeypatch.setattr(sess, '_new_curl_session', lambda: BoomCurl())
    monkeypatch.setattr(sess, '_new_requests_session', lambda: FakeReqSession())

    assert sess.using_impersonation is True
    assert sess.get('https://example.test') is sentinel
    assert sess.using_impersonation is False  # fallback odnotowany


def test_sessions_are_per_thread():
    sess = ImpersonatedSession(headers={})
    seen = {}

    def grab(name):
        seen[name] = id(sess._requests_session())

    t1 = threading.Thread(target=grab, args=('a',))
    t2 = threading.Thread(target=grab, args=('b',))
    t1.start(); t2.start(); t1.join(); t2.join()

    # Każdy wątek dostaje własny obiekt sesji (curl_cffi nie jest thread-safe).
    assert seen['a'] != seen['b']

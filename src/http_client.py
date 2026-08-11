"""
Klient HTTP z impersonacją TLS (curl_cffi) i fallbackiem na requests.

Po co to jest
-------------
OLX serwuje listing przez CloudFront/AWS WAF i od 2026-08-11 zaczął zwracać
`403 Request blocked` na requesty scrapera ze standardowym, pythonowym
fingerprintem TLS (JA3 biblioteki `requests`/OpenSSL jest charakterystyczny).
`curl_cffi` z `impersonate="chrome"` wysyła ClientHello nieodróżnialny od
prawdziwego Chrome'a, więc reguła typu „pythonowy fingerprint + IP datacenter"
go nie łapie.

Fallback
--------
Gdy `curl_cffi` jest niedostępny (brak paczki / problem z biblioteką natywną),
albo impersonowany handshake padnie na poziomie transportu, spadamy na
`requests`. Lepiej skanować gorszym fingerprintem niż nie skanować wcale —
a bezpiecznik przed masową dezaktywacją i tak wychwyci ewentualne 0 ofert.

UWAGA: odpowiedź 403 to normalny wynik `.get()` (wyjątek leci dopiero z
`raise_for_status()` u wywołującego), więc fallback transportowy NIE odpala się
na blokadzie — blokada jest wykrywana normalnie jako 0 ofert.

Wątki
-----
Scraper pobiera szczegóły ofert w `ThreadPoolExecutor`. Session `curl_cffi`
trzyma jeden uchwyt curl i NIE jest bezpieczna między wątkami, dlatego każdy
wątek dostaje własną sesję przez `threading.local()`.
"""

import threading

import requests

# Cel impersonacji. „chrome" = najnowszy profil Chrome znany danej wersji
# curl_cffi (TLS + kolejność nagłówków HTTP/2).
IMPERSONATE_TARGET = "chrome"

try:
    from curl_cffi import requests as _curl_requests
    from curl_cffi.requests.exceptions import RequestException as _CurlRequestException
    CURL_CFFI_AVAILABLE = True
except Exception:  # ImportError lub błąd ładowania biblioteki natywnej
    _curl_requests = None
    _CurlRequestException = None
    CURL_CFFI_AVAILABLE = False


# Krotka wyjątków sieciowych OBU backendów — do `except http_client.RequestError`.
# curl_cffi: HTTPError/ConnectionError/Timeout/SSLError dziedziczą po RequestException.
if CURL_CFFI_AVAILABLE:
    RequestError = (requests.RequestException, _CurlRequestException)
else:
    RequestError = (requests.RequestException,)


class ImpersonatedSession:
    """
    Sesja HTTP zgodna z API `requests.Session` (`.headers`, `.get`, `.close`),
    która pod spodem podszywa się pod TLS Chrome'a (curl_cffi), a przy jego
    braku/awarii używa `requests`.

    Drop-in tam, gdzie kod robił `requests.Session()` + `.headers.update(...)`.
    """

    def __init__(self, headers=None, impersonate=IMPERSONATE_TARGET):
        self.headers = dict(headers or {})
        self.impersonate = impersonate
        # Telemetria (best-effort, bez locka): czy realnie używamy impersonacji.
        self.using_impersonation = CURL_CFFI_AVAILABLE
        self._local = threading.local()

    # --- fabryki sesji per-wątek (osobne metody, żeby dały się mockować) ---

    def _new_curl_session(self):
        session = _curl_requests.Session(impersonate=self.impersonate)
        session.headers.update(self.headers)
        return session

    def _new_requests_session(self):
        session = requests.Session()
        session.headers.update(self.headers)
        return session

    def _curl_session(self):
        session = getattr(self._local, "curl", None)
        if session is None:
            session = self._new_curl_session()
            self._local.curl = session
        return session

    def _requests_session(self):
        session = getattr(self._local, "req", None)
        if session is None:
            session = self._new_requests_session()
            self._local.req = session
        return session

    # --- API ---

    def get(self, url, **kwargs):
        if not CURL_CFFI_AVAILABLE:
            return self._requests_session().get(url, **kwargs)
        try:
            return self._curl_session().get(url, **kwargs)
        except _CurlRequestException:
            # Impersowany handshake padł na poziomie transportu (nie HTTP 4xx —
            # te wracają jako normalna odpowiedź). Nie gubimy skanu: dokańczamy
            # zwykłym requests. Blokada 403 tu NIE trafia, więc jej nie maskujemy.
            self.using_impersonation = False
            return self._requests_session().get(url, **kwargs)

    def close(self):
        for attr in ("curl", "req"):
            session = getattr(self._local, attr, None)
            if session is not None:
                try:
                    session.close()
                except Exception:
                    pass
                setattr(self._local, attr, None)


def create_session(headers=None, impersonate=IMPERSONATE_TARGET):
    """Skrót fabryczny — czytelniejszy w miejscu użycia niż konstruktor."""
    return ImpersonatedSession(headers=headers, impersonate=impersonate)


if __name__ == "__main__":
    # Szybki podgląd: który backend jest aktywny i jak OLX odpowiada.
    print(f"curl_cffi dostępny: {CURL_CFFI_AVAILABLE} (impersonate={IMPERSONATE_TARGET})")
    s = create_session(headers={
        "Accept-Language": "pl,en-US;q=0.7,en;q=0.3",
    })
    try:
        r = s.get("https://www.olx.pl/nieruchomosci/mieszkania/wynajem/lublin/", timeout=20)
        print(f"status={r.status_code} len={len(r.text)} "
              f"oferty={r.text.count('/d/oferta/')} impersonacja={s.using_impersonation}")
    except RequestError as e:
        print(f"błąd sieci: {type(e).__name__}: {e}")

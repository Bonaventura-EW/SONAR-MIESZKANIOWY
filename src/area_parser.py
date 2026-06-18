#!/usr/bin/env python3
"""Ekstrakcja metrażu (m²), liczby pokoi i dzielnicy z treści ogłoszeń.

OLX nie udostępnia tych pól w sposób strukturalny dla najmu mieszkań w naszym
scraperze — siedzą w wolnym tekście opisu/tytułu. Ten moduł wyciąga je regexem
z sensownymi ograniczeniami (walidacja zakresów), na potrzeby podstrony
"Analiza cen wg metrażu" (cena za m², przedziały, dzielnice).

Funkcje są czyste (bez I/O) i testowalne — patrz tests/test_area_parser.py oraz
inline-testy w `if __name__ == "__main__"`.
"""

import re

# Powierzchnia: "47m²", "47 m2", "47,5 m kw", "pow. 47 metrów kwadratowych", "mkw".
# Wymagamy jednostki metrowej tuż po liczbie — sama liczba (np. "piętro 3") nie liczy się.
_AREA_RE = re.compile(
    r'(\d{1,3}(?:[.,]\d{1,2})?)\s*(?:m\s?[²2]\b|m\s?kw|mkw|m\.kw|metr(?:ów|y|a)?\s*kw)',
    re.IGNORECASE,
)
_AREA_MIN, _AREA_MAX = 8.0, 300.0  # odrzuca śmieci (np. "100 zł", numer telefonu)

# Liczba pokoi: "2 pokojowe", "2-pok", "kawalerka" (=1).
_ROOM_RE = re.compile(r'(\d)\s*[-\s]?\s*pok', re.IGNORECASE)
_KAWALERKA_RE = re.compile(r'kawalerk|garsonier', re.IGNORECASE)

# Dzielnice/osiedla Lublina. Kolejność = priorytet dopasowania (dłuższe/bardziej
# specyficzne najpierw, by "Stare Miasto" nie przegrało ze "Śródmieście" itp.).
# Wartość = nazwa kanoniczna wyświetlana użytkownikowi.
DISTRICTS = [
    ("śródmieście", "Śródmieście"),
    ("stare miasto", "Stare Miasto"),
    ("kalinowszczyzna", "Kalinowszczyzna"),
    ("konstantynów", "Konstantynów"),
    ("ponikwoda", "Ponikwoda"),
    ("bronowice", "Bronowice"),
    ("kośminek", "Kośminek"),
    ("dziesiąta", "Dziesiąta"),
    ("abramowice", "Abramowice"),
    ("zemborzyce", "Zemborzyce"),
    ("czechów", "Czechów"),
    ("wieniawa", "Wieniawa"),
    ("sławinek", "Sławinek"),
    ("sławin", "Sławin"),
    ("wrotków", "Wrotków"),
    ("węglin", "Węglin"),
    ("tatary", "Tatary"),
    ("felin", "Felin"),
    ("szerokie", "Szerokie"),
    ("czuby", "Czuby"),
    ("rury", "Rury"),
    ("lsm", "LSM"),
]


def extract_area(offer):
    """Zwraca powierzchnię w m² (float) lub None.

    Bierze pierwsze trafienie w zakresie [8, 300] m² — pierwsza wzmianka w opisie
    to zwykle metraż mieszkania (kolejne bywają o piwnicy/balkonie).
    """
    text = _text_of(offer)
    for m in _AREA_RE.finditer(text):
        try:
            val = float(m.group(1).replace(',', '.'))
        except ValueError:
            continue
        if _AREA_MIN <= val <= _AREA_MAX:
            return val
    return None


def extract_rooms(offer):
    """Zwraca liczbę pokoi (int 1–6) lub None. 'kawalerka'/'garsoniera' = 1."""
    text = _text_of(offer)
    m = _ROOM_RE.search(text)
    if m:
        r = int(m.group(1))
        if 1 <= r <= 6:
            return r
    if _KAWALERKA_RE.search(text):
        return 1
    return None


def extract_district(offer):
    """Zwraca kanoniczną nazwę dzielnicy Lublina lub None.

    Szuka w opisie i adresie (pole address.full). Dopasowanie po pierwszym
    trafieniu z listy DISTRICTS (uporządkowanej wg priorytetu)."""
    text = _text_of(offer).lower()
    for needle, canon in DISTRICTS:
        if needle in text:
            return canon
    return None


def _text_of(offer):
    """Łączy opis + adres oferty w jeden tekst do przeszukania."""
    desc = offer.get('description') or ''
    addr = (offer.get('address') or {}).get('full') or ''
    return f"{desc} {addr}"


if __name__ == '__main__':
    # Inline-testy (uruchom: `cd src && python area_parser.py`).
    cases_area = [
        ({'description': 'mieszkanie o powierzchni 47m², po remoncie'}, 47.0),
        ({'description': 'Kawalerka 28,5 m2 w centrum'}, 28.5),
        ({'description': 'pow. 62 metrów kwadratowych, 3 pokoje'}, 62.0),
        ({'description': 'do wynajęcia 53 mkw'}, 53.0),
        ({'description': 'cena 2000 zł, kontakt 530123456'}, None),  # brak jednostki m²
        ({'description': 'ogromne 999 m2'}, None),  # poza zakresem
    ]
    cases_rooms = [
        ({'description': '2-pokojowe mieszkanie'}, 2),
        ({'description': 'przestronne 3 pokoje'}, 3),
        ({'description': 'przytulna kawalerka'}, 1),
        ({'description': 'mieszkanie po remoncie'}, None),
    ]
    cases_dist = [
        ({'description': 'mieszkanie na LSM, blisko parku'}, 'LSM'),
        ({'description': 'Stare Miasto, kamienica'}, 'Stare Miasto'),
        ({'address': {'full': 'Czechów Północny'}}, 'Czechów'),
        ({'description': 'spokojna okolica'}, None),
    ]
    ok = fail = 0
    for fn, cases in ((extract_area, cases_area), (extract_rooms, cases_rooms),
                      (extract_district, cases_dist)):
        for offer, expected in cases:
            got = fn(offer)
            if got == expected:
                ok += 1
            else:
                fail += 1
                print(f"FAIL {fn.__name__}({offer}) = {got!r}, oczekiwano {expected!r}")
    print(f"\n{fn.__name__ if False else 'area_parser'}: OK={ok} FAIL={fail}")

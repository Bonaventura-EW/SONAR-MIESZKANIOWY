#!/usr/bin/env python3
"""Historia reaktywacji ofert — zapis (skan) i odczyt (generatory).

Pole `reactivated_at` trzyma tylko OSTATNI powrót oferty na rynek i jest
nadpisywane przy każdym kolejnym. Do wykresu „ile ofert wraca" to za mało:
oferta, która wróciła w czerwcu i jeszcze raz w sierpniu, widnieje wyłącznie
w sierpniu, więc starsze dni systematycznie się wypłukują. Zmierzone na bazie
2026-08-09: ~15 reaktywacji/dzień w połowie lipca vs 85 w dniu pomiaru — to
nie trend rynku, tylko nadpisywanie jednego pola.

Dlatego od 2026-08-09 każdy powrót dopisujemy do listy `reactivation_dates`,
razem z długością nieobecności (`gap_h`). Gap jest tu kluczowy: scraper
potrafi zgubić ofertę z listingu na jeden skan i odzyskać ją przy następnym
(~55 takich „reaktywacji" na skan przy ~710 aktywnych ofertach) — to szum
pipeline'u, nie powrót ogłoszenia na rynek. Zapisujemy każdy powrót surowo,
a filtrowanie po `gap_h` zostawiamy konsumentowi danych (`trend_generator`),
żeby zmiana progu nie wymagała ponownego zbierania historii.

Format wpisu: {'at': '<iso>', 'gap_h': 5.2, 'src': 'rescrape'}. `gap_h` bywa
nieobecne — tak wygląda historia sprzed tej zmiany (backfill z `reactivated_at`)
i powroty, przy których nie dało się odczytać poprzedniego `last_seen`.
"""

from datetime import date, datetime

# Ile wpisów trzymamy na ofertę. Oferta żyje zwykle ~30 dni, a dedup dzienny
# daje maksymalnie 1 wpis/dzień — 60 to zapas na rekordzistki, przy okazji
# pilnujący, żeby offers.json nie puchł od ofert-zombie.
MAX_ENTRIES = 60

# Próg „realnego" powrotu. Skany chodzą 3×/dzień (9:17/15:17/21:17), więc
# zgubienie oferty na jeden skan to przerwa ~6 h; powrót po ≥24 h oznacza,
# że ogłoszenia nie było w kilku kolejnych skanach — to już nieobecność
# na rynku, a nie mrugnięcie listingu.
MIN_REAL_GAP_HOURS = 24.0

# Źródła, które z definicji NIE są powrotem oferty na rynek.
# 'verification' = ofertę oznaczyliśmy jako nieaktywną, po czym jej strona
# szczegółów odpowiedziała „InStock" — czyli ogłoszenie cały czas było na OLX,
# tylko wypadło z naszego listingu (skan bierze 50 stron, przy ~720 ofertach
# kolejność potrafi wypchnąć ogłoszenie poza to okno). Zmierzone 2026-08-09:
# ~48 takich „reaktywacji" na skan wobec 0–9 realnych powrotów z listingu.
NOISE_SOURCES = ('verification',)


def _parse(value):
    """ISO → datetime; None gdy pole puste albo uszkodzone."""
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _day(value):
    dt = _parse(value)
    return dt.date() if dt else None


def gap_hours(prev_last_seen, now_iso):
    """Długość nieobecności w godzinach; None gdy nie da się jej policzyć."""
    before, after = _parse(prev_last_seen), _parse(now_iso)
    if before is None or after is None:
        return None
    try:
        delta = (after - before).total_seconds() / 3600
    except TypeError:      # naive vs aware — w bazie zdarzają się oba
        return None
    return round(delta, 1) if delta >= 0 else None


def record(offer, now_iso, source, prev_last_seen=None):
    """Zapisuje reaktywację oferty (mutuje `offer`).

    Ustawia `reactivated_at`/`reactivation_source` jak dotąd i dokłada wpis do
    `reactivation_dates`. `prev_last_seen` to `last_seen` SPRZED aktualizacji —
    stąd bierze się `gap_h`, więc wołający musi zapamiętać starą wartość, zanim
    wpisze do oferty świeżą.
    """
    previous_at = offer.get('reactivated_at')
    offer['reactivated_at'] = now_iso
    offer['reactivation_source'] = source

    log = offer.get('reactivation_dates')
    if not isinstance(log, list):
        # Oferta sprzed tej zmiany: zaczynamy listę od znanej ostatniej
        # reaktywacji (bez gapu — nie mamy jak go odtworzyć wstecz).
        log = [{'at': previous_at}] if previous_at else []

    entry = {'at': now_iso, 'src': source}
    gap = gap_hours(prev_last_seen, now_iso)
    if gap is not None:
        entry['gap_h'] = gap

    today = _day(now_iso)
    last = log[-1] if log else None
    if last and today and _day(last.get('at')) == today:
        # Kilka powrotów tego samego dnia = ta sama nieobecność widziana przez
        # kolejne skany. Zostawiamy pierwszy wpis (to on niesie prawdziwą
        # długość przerwy), podnosząc gap do najdłuższego znanego. Źródło
        # bierzemy „mocniejsze": powrót w listingu bije weryfikację, bo mówi
        # więcej o rynku niż nasza własna pomyłka w dezaktywacji.
        gaps = [g for g in (last.get('gap_h'), gap) if g is not None]
        if gaps:
            last['gap_h'] = max(gaps)
        if last.get('src') in NOISE_SOURCES and source not in NOISE_SOURCES:
            last['src'] = source
    else:
        log.append(entry)

    offer['reactivation_dates'] = log[-MAX_ENTRIES:]


def entries(offer):
    """Wpisy historii jako [{'at':…, 'gap_h':…}] — także dla ofert sprzed listy."""
    log = offer.get('reactivation_dates')
    out = []
    if isinstance(log, list):
        for item in log:
            if isinstance(item, dict) and item.get('at'):
                out.append(item)
            elif isinstance(item, str):       # tolerancja na goły ISO
                out.append({'at': item})
    if not out and offer.get('reactivated_at'):
        out.append({'at': offer['reactivated_at']})
    return out


def measured_days(offer):
    """Dni z wpisami niosącymi `gap_h` — czyli te, dla których mamy pełny pomiar."""
    return sorted({_day(e['at']) for e in entries(offer)
                   if e.get('gap_h') is not None and _day(e.get('at'))})


def return_days(offer, min_gap_hours=MIN_REAL_GAP_HOURS, skip_days=()):
    """Dni, w których oferta realnie wróciła na rynek (posortowane, bez powtórek).

    Powrót liczy się, gdy oferty nie było ≥ `min_gap_hours` i wróciła w listingu
    (źródła spoza NOISE_SOURCES). Wpisy bez `gap_h` nie liczą się w ogóle:
    to historia sprzed 2026-08-09, odtworzona z nadpisywanego `reactivated_at`,
    więc mówi tylko „kiedy oferta wróciła OSTATNI raz" — dzień po dniu jest nie
    do odróżnienia od szumu (zmierzone: 15/dzień w połowie lipca vs 85 w dniu
    pomiaru, przy stałym ruchu na rynku). `skip_days` wycina dni-artefakty
    pipeline'u (patrz `trend_generator`).
    """
    days = set()
    for item in entries(offer):
        day = _day(item.get('at'))
        gap = item.get('gap_h')
        if day is None or day in skip_days or gap is None:
            continue
        if gap < min_gap_hours or item.get('src') in NOISE_SOURCES:
            continue
        days.add(day)
    return sorted(days)


def first_return_day(offer, min_gap_hours=MIN_REAL_GAP_HOURS, skip_days=()):
    """Pierwszy dzień realnego powrotu (albo None) — do podziału na pasma."""
    days = return_days(offer, min_gap_hours, skip_days)
    return days[0] if days else None


if __name__ == '__main__':
    ok = fail = 0

    def check(label, condition):
        global ok, fail
        if condition:
            ok += 1
            print(f"   ✅ {label}")
        else:
            fail += 1
            print(f"   ❌ {label}")

    o = {'last_seen': '2026-08-01T10:00:00+02:00'}
    record(o, '2026-08-03T10:00:00+02:00', 'rescrape', o['last_seen'])
    check('gap liczony z poprzedniego last_seen', o['reactivation_dates'][0]['gap_h'] == 48.0)
    check('reactivated_at nadal ustawiane', o['reactivated_at'] == '2026-08-03T10:00:00+02:00')

    record(o, '2026-08-03T21:00:00+02:00', 'rescrape', '2026-08-03T15:00:00+02:00')
    check('dedup dzienny', len(o['reactivation_dates']) == 1)
    check('gap = najdłuższy tego dnia', o['reactivation_dates'][0]['gap_h'] == 48.0)

    record(o, '2026-08-05T09:00:00+02:00', 'rescrape', '2026-08-05T03:00:00+02:00')
    check('krótka przerwa nie jest powrotem',
          return_days(o) == [date(2026, 8, 3)])
    check('artefaktowy dzień wycięty',
          return_days(o, skip_days={date(2026, 8, 3)}) == [])

    noise = {'last_seen': '2026-08-01T10:00:00+02:00'}
    record(noise, '2026-08-06T10:00:00+02:00', 'verification', noise['last_seen'])
    check('weryfikacja to nie powrót na rynek', return_days(noise) == [])
    check('ale zostaje w surowej historii', len(entries(noise)) == 1)

    legacy = {'reactivated_at': '2026-06-01T10:00:00+02:00'}
    check('historia bez gapu nie udaje pomiaru', return_days(legacy) == [])
    check('stara data nadal czytelna',
          [e['at'] for e in entries(legacy)] == ['2026-06-01T10:00:00+02:00'])
    record(legacy, '2026-06-10T10:00:00+02:00', 'rescrape', '2026-06-02T10:00:00+02:00')
    check('backfill zachowuje starą datę',
          [e['at'] for e in legacy['reactivation_dates']] ==
          ['2026-06-01T10:00:00+02:00', '2026-06-10T10:00:00+02:00'])
    check('pomiar zaczyna się od wpisu z gapem',
          measured_days(legacy) == [date(2026, 6, 10)])

    print(f"\nOK: {ok} / FAIL: {fail}")

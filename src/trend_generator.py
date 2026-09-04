#!/usr/bin/env python3
"""
Generator trend_data.json dla SONAR MIESZKANIOWY

Buduje DZIENNY szereg czasowy liczby aktywnych ofert mieszkań przez
rekonstrukcję z data/offers.json: dla każdego dnia D liczy ile ofert "żyło"
tego dnia (first_seen <= D <= last_seen; dla wciąż aktywnych granicą jest
ostatni dzień skanu).

To "indeks podaży" w stylu betonometr.pl: ile żywych ofert wynajmu mieszkań
w Lublinie jest danego dnia na rynku. Port strony `trend.html` z siostrzanego
SONAR POKOJOWY.

Dlaczego nie scan_history.json: tam trzymamy tylko metadane skanów (liczba
ofert w danym skanie), bez możliwości odtworzenia dnia po dniu wstecz.
offers.json sięga 29.04.2026 (seed bazy), ale rekonstrukcja sprzed 16.05 jest
zaniżona — do tego dnia parser adresów odrzucał setki ofert na skan
(patrz CHANGELOG 2026-05-16: przywrócenie `extract_street_only`, whitelist ulic),
więc w bazie po prostu ich nie ma. Odcinamy ten okres i rysujemy tylko
wiarygodny zakres.
"""

import json
from collections.abc import Mapping
from datetime import datetime, date, timedelta
from pathlib import Path

import paths
import reactivation_log
from atomic_json import atomic_write_json

TITLE = "Lublin – mieszkania: wynajem"
UNIT = "ofert"

# Pierwszy wiarygodny dzień (po naprawach parsera adresów z 16.05.2026).
# Wszystko wcześniej to artefakt zbierania danych, nie obraz rynku.
RELIABLE_START = date(2026, 5, 16)

# Dni, w których „reaktywacja" była awarią pipeline'u, nie powrotem na rynek.
# 2026-08-05 06:31: częściowa blokada OLX zdjęła 409 ofert (aktywne 706 → 349),
# a kolejne skany tego samego dnia przywróciły 308 z nich (patrz CHANGELOG,
# „martwa strefa ochrony przed dezaktywacją"). Te ogłoszenia nigdy nie zniknęły
# z rynku — policzone jako powroty dałyby dzienny pik 10× ponad normę i wrzuciły
# 232 wciąż aktywne oferty do pasma „recykling".
# Świeże wpisy bronią się same (nieobecność < 24 h → nie liczy się jako powrót);
# ta lista łata historię sprzed 2026-08-09, gdzie długości przerw nie znamy.
REACTIVATION_ARTIFACT_DAYS = frozenset({date(2026, 8, 5)})

# Dni, w których „odpływ" (ile ofert zniknęło) to artefakt cyklu
# blokada→odblokowanie OLX, nie obraz rynku.
# 2026-08-11: od ~13:00 OLX/CloudFront zwracał 403 (blokada TLS-fingerprintu),
# przez ~10 h dezaktywacja była wstrzymana (ochrona przed masową dezaktywacją).
# Skan naprawczy o 22:45 (po wdrożeniu impersonacji curl_cffi) zdezaktywował
# naraz 82 nagromadzone oferty, a krok weryfikacji nieaktywnych padł 50/50
# (te same 403 na stronach ofert), więc nie odsiał fałszywych dezaktywacji.
# Efekt: 98 zniknięć jednego dnia (norma 28–50), z czego 86 to świeże,
# niezweryfikowane wpisy — sztuczny „rekord". Świeże dni bronią się przez
# pomiar (przyszłe reaktywacje przesuną fałszywe poza 11.08), ale sam 11.08
# ma zamrożony `last_seen`, więc maskujemy go na stałe — jak 2026-08-05 powroty.
OUTFLOW_ARTIFACT_DAYS = frozenset({date(2026, 8, 11)})

# Ile skanów planujemy na dobę (cron `17 7,13,19 * * *` → 9:17/15:17/21:17).
# Dzień, w którym zakończyło się MNIEJ przebiegów, widział tylko wycinek doby:
# oferty urodzone i zmarłe w nieobserwowanym oknie dostają daty z sąsiedniego
# dnia, więc każda metryka dzienna jest z niego zaniżona. Zmierzone 2026-09-04
# na 18/19/31.08 (po 2 skany, w tym 18.08 tylko 05:30 i 09:56): Indeks leży
# średnio 17,5 oferty POD średnią sąsiednich dni, przy +7,1 dla dni pełnych.
SCANS_PER_DAY = 3

# Ile ostatnich ZMIERZONYCH dni wchodzi do średniej „X/dzień" pod wykresami
# przepływu. Średnia po całej historii mieszała trzy różne reżimy dezaktywacji
# (przed 12.08, weryfikacja linków, `MAX_MISSING_DAYS` od 02.09) i nie opisywała
# żadnego realnego okresu — 26,1/dzień wobec ~43/dzień w ostatnim miesiącu.
# UWAGA: to sufit okna, nie jego długość. Metryka zamaskowana na części tych dni
# (powroty mierzymy dopiero od 11.08) uśrednia po mniejszej liczbie dni, więc
# `rate` z dwóch różnych wykresów NIE JEST addytywne — stąd `rate_days`
# w wyniku i „(ost. N dni)" przy każdej liczbie na stronie.
FLOW_RATE_WINDOW_DAYS = 30

# Dzień, w którym „nowe oferty" to zaległość parsera, a nie napływ z rynku.
# 16.05.2026 wróciło do bazy 97 ofert (sąsiednie dni: 16–26) — te same setki
# ogłoszeń, przez które odcinamy historię sprzed RELIABLE_START. Do Indeksu
# wchodzą normalnie (żyły na OLX), ale ich `first_seen` mówi o naszym parserze,
# nie o rynku, więc z wykresu napływu wypadają — inaczej stoją tam jako rekord.
NEW_OFFER_ARTIFACT_DAYS = frozenset({RELIABLE_START})


def _day_ms(d: date) -> int:
    """Epoch (ms) dla południa danego dnia — punkt ląduje w środku dnia na osi."""
    return int(datetime(d.year, d.month, d.day, 12, 0).timestamp() * 1000)


def _safe_dt(iso_string):
    """ISO → datetime; None zamiast wyjątku (w bazie trafiają się śmieciowe daty)."""
    try:
        return datetime.fromisoformat(iso_string)
    except (ValueError, TypeError):
        return None


def _safe_day(iso_string):
    """ISO → date; None zamiast wyjątku (w bazie trafiają się śmieciowe daty)."""
    dt = _safe_dt(iso_string)
    return dt.date() if dt else None


def _daily_range(start, end):
    """Lista kolejnych dni [start..end] (włącznie). Pusta, gdy end < start."""
    days, day = [], start
    while day <= end:
        days.append(day)
        day += timedelta(days=1)
    return days


def _absence_intervals(offer):
    """Dni, w których oferty NIE było na rynku, odczytane z historii powrotów.

    Powrót po realnej nieobecności (`gap_h` ≥ próg) znaczy, że między ostatnim
    widzeniem a powrotem ogłoszenia na OLX nie było. Jeden ciągły okres
    `first_seen..last_seen` liczyłby te dni jako żywe — stąd wycinamy je
    z okresu życia. Powroty ze źródła `verification` NIE są nieobecnością:
    to nasza własna pomyłka przy dezaktywacji, ogłoszenie cały czas żyło
    (patrz `reactivation_log.NOISE_SOURCES`).
    """
    gaps = []
    for entry in reactivation_log.entries(offer):
        gap_h = entry.get('gap_h')
        if gap_h is None or gap_h < reactivation_log.MIN_REAL_GAP_HOURS:
            continue
        if entry.get('src') in reactivation_log.NOISE_SOURCES:
            continue
        back_dt = _safe_dt(entry.get('at'))
        if back_dt is None:
            continue
        if back_dt.date() in REACTIVATION_ARTIFACT_DAYS:
            # Dzień-artefakt: te oferty nigdy nie zeszły z OLX, tylko my
            # zgubiliśmy je przy częściowej blokadzie. Skoro powrót nie liczy
            # się do napływu (`REACTIVATION_ARTIFACT_DAYS`), to i nieobecność
            # nie może wyciąć dziury w Indeksie — inaczej wykresy przestają się
            # domykać dokładnie w dniu, o którym wiemy, że jest zmyślony.
            continue
        # FIX 2026-09-04: dzień zniknięcia odejmujemy w GODZINACH, a nie przez
        # `int(gap_h // 24)`. Skany chodzą 9:17/15:17/21:17, więc powrót bywa
        # o pół doby wcześniej w dobie niż ostatnie widzenie i dzielenie
        # całkowite gubiło całą dobę nieobecności — 78 z 245 realnych powrotów
        # w bazie (32%). Przy przerwie 24–48 h przerwa znikała wtedy zupełnie:
        # oferta była naraz „wróciła na rynek" (napływ) i „ani na chwilę nie
        # zniknęła" (Indeks). `at` niesie pełny timestamp, a `gap_h` dokładną
        # różnicę, więc odtworzenie dnia jest bezstratne.
        back = back_dt.date()
        gone = (back_dt - timedelta(hours=gap_h)).date()
        # Dzień zniknięcia i dzień powrotu oferta jeszcze/już żyła — wycinamy
        # tylko pełne dni nieobecności między nimi.
        first_missing, last_missing = gone + timedelta(days=1), back - timedelta(days=1)
        if last_missing >= first_missing:
            gaps.append((first_missing, last_missing))
    return sorted(gaps)


def _split_span(start, end, gaps):
    """Okres życia [start, end] pocięty przerwami → lista rozłącznych odcinków."""
    pieces, cursor = [], start
    for gone, back in gaps:
        if back < cursor or gone > end:
            continue
        if gone > cursor:
            pieces.append((cursor, min(gone - timedelta(days=1), end)))
        cursor = max(cursor, back + timedelta(days=1))
        if cursor > end:
            return pieces
    if cursor <= end:
        pieces.append((cursor, end))
    return pieces


def _entry_days(offer):
    """(dzień wejścia na rynek, dni powrotów) — starty odcinków życia oferty.

    Napływ czytamy z tych samych odcinków, z których liczy się Indeks i odpływ,
    a nie wprost z `reactivation_log`. Wykres ma rozdzielczość DNIA, więc powrót
    po 24 h, który nie objął ani jednej pełnej doby (ostatnie widzenie 21:17,
    powrót nazajutrz 21:20), nie zdejmuje oferty z żadnego dnia Indeksu —
    liczony jako napływ rozjeżdżał bilans o ~0,5 oferty dziennie. Jedno źródło
    prawdy o wejściach i wyjściach = bilans domyka się z definicji.
    """
    start = _safe_day(offer.get('first_seen'))
    end = _safe_day(offer.get('last_seen'))
    if start is None or end is None:
        return None, []
    if end < start:
        end = start
    pieces = _split_span(start, end, _absence_intervals(offer))
    if not pieces:
        return None, []
    return pieces[0][0], [piece_start for piece_start, _ in pieces[1:]]


def _offer_spans(offers):
    """[(oferta, start, end), ...] — okresy życia ofert razem z samą ofertą.

    Wersja z ofertą jest potrzebna pasmom (`build_bands`), które muszą zajrzeć
    do historii reaktywacji; `build_spans` zwraca z tego same okresy. Oferta
    z przerwą w życiu daje WIĘCEJ NIŻ JEDEN odcinek — odcinki są rozłączne,
    więc każdy dzień liczy ofertę najwyżej raz.

    FIX 2026-09-02: koniec odcinka to zawsze `last_seen`, także dla ofert
    z `active=True`. Wcześniej aktywne ciągnęły się do dnia ostatniego skanu,
    co doliczało do KAŻDEGO dnia oferty, których scraper od tygodni nie widzi
    w listingu, a które czekają w kolejce do sprawdzenia linku (2026-09-02:
    1019 „aktywnych" wobec 774 ofert realnie zebranych z OLX — nadwyżka rosła
    od 18.08 wprost proporcjonalnie do kolejki `verification.candidates`).
    Skany chodzą 3×/dzień, więc pojedyncze zgubienie oferty przez paginację
    nie rusza `last_seen` z dokładnością do dnia — grace nie jest potrzebny.
    """
    today = max(
        (d for d in (_safe_day(o.get('last_seen')) for o in offers) if d),
        default=date.today(),
    )
    spans = []
    for o in offers:
        start = _safe_day(o.get('first_seen'))
        end = _safe_day(o.get('last_seen'))
        if start is None or end is None:
            continue
        if end < start:
            end = start
        for piece_start, piece_end in _split_span(start, end, _absence_intervals(o)):
            spans.append((o, piece_start, piece_end))
    return spans, today


def build_spans(offers):
    """[(start_date, end_date), ...] — okresy życia ofert, bez samych ofert.

    Koniec odcinka to zawsze `last_seen` (także dla `active=True`) — patrz
    `_offer_spans`. Oferta z realną przerwą daje więcej niż jeden odcinek.
    """
    spans, today = _offer_spans(offers)
    return [(start, end) for _, start, end in spans], today


def _scan_counts(scan_days):
    """Wejście generatorów → {dzień: liczba zakończonych skanów}.

    Przyjmuje mapę z `load_scan_counts`, ale też goły zbiór dni — tak wołają
    starsze testy i taki kształt miał kiedyś ten argument. Zbiór nie niesie
    liczby przebiegów, więc zakładamy dla niego pełne pokrycie.
    """
    if isinstance(scan_days, Mapping):
        return {day: count for day, count in scan_days.items() if day}
    return {day: SCANS_PER_DAY for day in (scan_days or ())}


def _scan_coverage(counts, today):
    """(dni_niepełne, ostatni_pełny_dzień) wg dziennika skanów.

    Dzień jest PEŁNY, gdy zakończyły się w nim wszystkie zaplanowane przebiegi
    (`SCANS_PER_DAY`). Niepełny — czy to zero skanów (awaria Actions, blokada
    OLX), czy jeden z trzech (doba jeszcze trwa) — pokazuje wycinek listingu
    i idzie do serii jako `None`, zamiast udawać załamanie rynku.

    FIX 2026-09-04: ostatni pełny dzień jest końcem WSZYSTKICH wykresów.
    Wcześniej dzień bieżący rysował się jak zamknięty, choć dopiero się zbierał:
    03.09 szedł 686 → 717 → 748 → 767 przez kolejne skany tej samej doby,
    a nagłówek pokazywał „1D: −84" rano i „−8" wieczorem (zmierzone na
    snapshotach `trend_data.json` z gita). Do 02.09 maskował to błąd
    przeciwnego znaku — aktywne oferty ciągnęły się do dnia ostatniego skanu.

    Pierwszy dzień dziennika pomijamy: historia trzyma ostatnie ~100 przebiegów,
    więc bywa ucięta w połowie doby i taki dzień wyglądałby na niepełny.
    """
    if not counts:
        return frozenset(), today
    window = _daily_range(min(counts) + timedelta(days=1), today)
    incomplete = frozenset(day for day in window
                           if counts.get(day, 0) < SCANS_PER_DAY)
    last_complete = next((day for day in reversed(window)
                          if day not in incomplete), None)
    # Same niepełne dni w oknie dziennika (albo okno puste) = nie ma czym ciąć;
    # zostawiamy zakres bez zmian, żeby awaria dziennika nie skasowała wykresu.
    return incomplete, last_complete or today


def _window(offers, scan_days=None):
    """Wspólny szkielet metryk: (odcinki życia, dni wykresu, dni niepełne).

    Wszystkie wykresy na zakładce liczą się na TEJ SAMEJ osi dni i z tą samą
    maską — dzięki temu suma pasm zgadza się z Indeksem, a odpływ z napływem.
    """
    spans, today = _offer_spans(offers)
    if not spans:
        return spans, [], frozenset()
    incomplete, last_complete = _scan_coverage(_scan_counts(scan_days), today)
    start = max(RELIABLE_START, min(start for _, start, _ in spans))
    return spans, _daily_range(start, last_complete), incomplete


def build_series(offers, scan_days=None):
    """Dzienna seria [[ms, liczba_ofert_na_rynku], ...] od RELIABLE_START.

    Dzień bez pełnego pokrycia skanami idzie do serii jako `None` — ApexCharts
    rysuje w tym miejscu przerwę zamiast fałszywego załamania rynku (patrz
    `_scan_coverage`). Seria kończy się na ostatnim PEŁNYM dniu, więc trwająca
    doba nie jest pokazywana jako zamknięta.
    """
    spans, days, incomplete = _window(offers, scan_days)
    if not days:
        return []
    return [[_day_ms(day),
             None if day in incomplete
             else sum(1 for _, start, end in spans if start <= day <= end)]
            for day in days]


def _flow_metric(counts, days, skip_days=frozenset()):
    """Wspólny kształt wykresu przepływu: seria dzienna + średnia 7 dni + statystyki.

    `counts` to {dzień: liczba}, `days` to oś czasu wykresu. Dni z `skip_days`
    trafiają do serii jako `None` (ApexCharts rysuje w tym miejscu przerwę)
    i nie wchodzą ani do średniej kroczącej, ani do statystyk — inaczej jeden
    dzień-artefakt zawyżyłby średnią i „rekord" na wiele miesięcy.
    """
    daily, avg, counted = [], [], []
    for i, day in enumerate(days):
        ms = _day_ms(day)
        if day in skip_days:
            daily.append([ms, None])
            avg.append([ms, None])
            continue
        value = counts.get(day, 0)
        daily.append([ms, value])
        counted.append((day, value))
        window = [counts.get(d, 0) for d in days[max(0, i - 6):i + 1] if d not in skip_days]
        avg.append([ms, round(sum(window) / len(window), 1) if window else 0])

    total = sum(v for _, v in counted)
    mx = max((v for _, v in counted), default=0)
    # dzień rekordu: ostatnie (najświeższe) wystąpienie maksimum
    record_day = next((d for d, v in reversed(counted) if v == mx),
                      days[0] if days else RELIABLE_START)
    # FIX 2026-09-04: „X/dzień" liczymy z ostatnich `FLOW_RATE_WINDOW_DAYS`
    # zmierzonych dni, nie z całej historii — patrz komentarz przy stałej.
    recent = counted[-FLOW_RATE_WINDOW_DAYS:]

    return {
        'daily': daily,
        'avg': avg,
        'total': total,
        'rate': round(sum(v for _, v in recent) / len(recent), 1) if recent else 0,
        'rate_days': len(recent),
        'rate_all': round(total / len(counted), 1) if counted else 0,
        'max_day': mx,
        'max_ts': _day_ms(record_day),
        'max_label': record_day.strftime('%d.%m'),
    }


def build_outflow(offers, scan_days=None):
    """Dzienny odpływ (ile ofert WYSZŁO z Indeksu danego dnia) + średnia 7 dni.

    „Wyjście" to koniec odcinka życia z `_offer_spans`, czyli ostatni dzień,
    w którym oferta liczyła się do Indeksu. Obejmuje jedno i drugie: zniknięcie
    z rynku na dobre ORAZ początek realnej nieobecności, z której ogłoszenie
    później wróci.

    FIX 2026-09-04: wcześniej liczyliśmy wyłącznie oferty `active=False` po ich
    `last_seen` i wykres rozjeżdżał się z Indeksem na dwa sposoby:
    - dezaktywacja przychodzi z opóźnieniem (kolejka linków, `MAX_MISSING_DAYS`),
      więc świeże dni dojrzewały jeszcze 2–3 doby wstecz — 01.09 pokazywał
      kolejno 6 → 40 → 43, a ostatnie punkty wykresu zawsze leżały za nisko;
    - wyjścia na czas nieobecności nie liczyły się W OGÓLE, choć powroty
      normalnie zasilały „Reaktywacje" i „Napływ całkowity". Za 12.08–03.09
      dawało to napływ 46,6/dzień wobec odpływu 40,3/dzień, czyli +146 ofert,
      podczas gdy Indeks urósł w tym czasie o 5.
    Teraz `Indeks(D) = Indeks(D−1) + napływ(D) − odpływ(D−1)` domyka się co do
    sztuki wszędzie poza dniami z maską.

    Ostatni dzień okna nie ma odpływu: koniec odcinka znaczy tam tylko „to nasza
    najświeższa obserwacja", a nie zniknięcie oferty — dlatego seria kończy się
    dobę przed Indeksem.
    """
    spans, days, incomplete = _window(offers, scan_days)
    if len(days) < 2:
        return None
    settled = days[:-1]
    first, last = settled[0], settled[-1]

    dep = {}
    for _, _, end in spans:
        if first <= end <= last:
            dep[end] = dep.get(end, 0) + 1

    # Dni-artefakty (blokada→odblokowanie) i dni o niepełnym pokryciu idą do
    # serii jako None: przerwa na wykresie zamiast sztucznego rekordu, i bez
    # wpływu na średnią oraz „rekord".
    return _flow_metric(dep, settled,
                        skip_days=OUTFLOW_ARTIFACT_DAYS | incomplete)


def measured_from(offers):
    """Pierwszy dzień, dla którego powroty ofert są zmierzone, a nie odtworzone.

    Do 2026-08-09 baza trzymała jedną, nadpisywaną datę reaktywacji na ofertę,
    więc dnia „ile ofert wróciło" nie da się z niej odtworzyć — im starszy
    dzień, tym więcej powrotów wyparowało (zmierzone: 15/dzień w połowie lipca
    vs 85 w dniu pomiaru, przy niezmienionym ruchu). Od kiedy `reactivation_log`
    zapisuje każdy powrót z długością nieobecności, liczby są prawdziwe —
    i tylko ten zakres pokazujemy.

    Pierwszy dzień zapisu jest urwany (skany chodzą 3×/dzień, a zapis rusza od
    najbliższego), więc oś zaczynamy od następnego — inaczej seria startowałaby
    sztucznym dołkiem.
    """
    starts = [days[0] for days in
              (reactivation_log.measured_days(o) for o in offers) if days]
    return min(starts) + timedelta(days=1) if starts else None


def build_inflow(offers, scan_days=None):
    """Napływ ofert: nowe / reaktywacje / suma — dziennie + średnia 7 dni.

    - `new`   — ogłoszenia widziane pierwszy raz (`first_seen` = ten dzień),
    - `react` — powroty na rynek po realnej nieobecności,
    - `new_react` — suma jednego i drugiego, czyli cały dopływ ofert.

    Jedno i drugie czytamy ze startów odcinków życia (`_entry_days`), tych
    samych, na których stoi Indeks i odpływ — inaczej wykresy nie domykają się
    w bilans (patrz `build_outflow`).

    Dni bez pomiaru powrotów (przed `measured_from`), dni-artefakty
    (`REACTIVATION_ARTIFACT_DAYS`, `NEW_OFFER_ARTIFACT_DAYS`) i dni o niepełnym
    pokryciu skanami idą do serii jako `None` — na wykresie widać w tym miejscu
    przerwę zamiast liczby, której nie umiemy obronić. Suma dziedziczy obie
    maski: „cały dopływ" bez powrotów byłby po prostu wykresem nowych ofert
    pod cudzą etykietą.
    """
    spans, days, incomplete = _window(offers, scan_days)
    if not days:
        return None
    window = set(days)

    new_counts, react_counts = {}, {}
    for o in offers:
        first, returns = _entry_days(o)
        if first in window:
            new_counts[first] = new_counts.get(first, 0) + 1
        for day in returns:
            if day in window:
                react_counts[day] = react_counts.get(day, 0) + 1

    both = {d: new_counts.get(d, 0) + react_counts.get(d, 0)
            for d in set(new_counts) | set(react_counts)}

    since = measured_from(offers)
    unmeasured = {d for d in days if since is None or d < since}
    new_skip = NEW_OFFER_ARTIFACT_DAYS | incomplete
    react_skip = REACTIVATION_ARTIFACT_DAYS | incomplete | unmeasured

    return {
        'new': _flow_metric(new_counts, days, new_skip),
        'react': _flow_metric(react_counts, days, react_skip),
        'new_react': _flow_metric(both, days, new_skip | react_skip),
        'measured_from': since.isoformat() if since else None,
    }


def build_bands(offers, scan_days=None):
    """Rozbicie indeksu na pasma: oferty świeże vs wracające z martwych.

    Oferta siedzi w paśmie „świeże" od pierwszego dnia życia, a do „recyklingu"
    przechodzi w dniu swojego pierwszego realnego powrotu na rynek i zostaje
    tam do końca. Suma pasm dzień po dniu = linia Indeksu (te same okresy
    życia), więc przełącznik na wykresie pokazuje rozbicie tej samej liczby,
    a nie inną metrykę.

    Pasma zaczynają się dopiero od `measured_from`: wcześniej nie wiadomo,
    które oferty już wróciły z martwych, więc wykres pokazywałby rosnące pasmo
    recyklingu tylko dlatego, że baza pamięta ostatni powrót każdej oferty.
    Oferty, które wróciły przed startem pomiaru, siedzą w paśmie „świeże"
    do swojego kolejnego powrotu — udział recyklingu jest więc zaniżony
    i dochodzi do prawdy w miarę wymiany ofert na rynku (~30 dni życia).
    """
    spans, window_days, incomplete = _window(offers, scan_days)
    if not window_days:
        return None
    since = measured_from(offers)
    if since is None:
        return None
    days = [d for d in window_days if d >= since]
    if not days:
        return None
    index = {day: i for i, day in enumerate(days)}
    fresh = [0] * len(days)
    recycled = [0] * len(days)

    for offer, start, end in spans:
        low, high = max(start, days[0]), min(end, days[-1])
        if high < low:
            continue
        first, last = index[low], index[high]
        # Pasma pytają o HISTORIĘ oferty („czy kiedykolwiek wróciła z martwych"),
        # nie o dzienne zdarzenie, więc czytają wprost z `reactivation_log`.
        # Napływ liczy się inaczej (`_entry_days`), bo tam musi się domykać
        # z odpływem — a powrót w dniu pojawienia się oferty nie daje osobnego
        # odcinka życia, choć dla pasma to nadal recykling.
        back = reactivation_log.first_return_day(
            offer, skip_days=REACTIVATION_ARTIFACT_DAYS)
        # Powrót sprzed okna wykresu liczy się od jego pierwszego dnia;
        # powrót po `high` (oferta wróciła i znów zniknęła) — wcale.
        split = index[max(back, low)] if back is not None and back <= high else None
        for i in range(first, last + 1):
            if split is not None and i >= split:
                recycled[i] += 1
            else:
                fresh[i] += 1

    # Ta sama maska co w Indeksie — inaczej po przełączeniu na „Rozbij" dzień
    # z niepełnym pokryciem pokazywałby słupek tam, gdzie „Suma" ma przerwę.
    def _masked(values):
        return [[_day_ms(d), None if d in incomplete else v]
                for d, v in zip(days, values)]

    return {'new': _masked(fresh), 'react': _masked(recycled)}


def _scanned_days(offers):
    """Dni, w których skan REALNIE zebrał dane (jakakolwiek oferta ma tam last_seen).

    Każdy skan podbija `last_seen` obecnych ofert, a dezaktywacja zamraża je na
    dniu zniknięcia — więc zbiór `last_seen` pokrywa dni z działającym skanem.
    Dzień bez skanu (awaria Actions, blokada OLX) miałby zero promowanych i
    rysowałby się jak realne załamanie metryki; taki dzień oznaczamy jako lukę.
    """
    days = set()
    for o in offers:
        d = _safe_day(o.get('last_seen'))
        if d:
            days.add(d)
    return days


def load_scan_counts(input_file) -> dict:
    """{dzień: liczba ZAKOŃCZONYCH skanów} wg data/scan_history.json.

    Źródło prawdy o pokryciu doby przebiegami — na nim stoi maska niepełnych
    dni (`_scan_coverage`). Historia trzyma ostatnie ~100 skanów (≈20–33 dni
    przy 3–6 przebiegach dziennie), więc o starszych dniach nie wie nic i tam
    zakładamy pełne pokrycie. Brak/uszkodzony plik = pusty słownik (metryki
    działają, tylko bez maski).
    """
    path = Path(input_file).parent / 'scan_history.json'
    counts = {}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            history = json.load(f)
    except (OSError, json.JSONDecodeError):
        return counts
    if isinstance(history, dict):
        history = history.get('scans', [])
    for scan in history or []:
        if scan.get('status') not in ('completed', 'warning'):
            continue
        d = _safe_day(scan.get('timestamp'))
        if d:
            counts[d] = counts.get(d, 0) + 1
    return counts


def load_scan_days(input_file) -> set:
    """Dni z jakimkolwiek zakończonym skanem (klucze `load_scan_counts`)."""
    return set(load_scan_counts(input_file))


def build_promoted(offers, series, scan_days=None):
    """Dzienna liczba ofert PROMOWANYCH (płatne wyróżnienie na listingu OLX).

    Źródło: `promoted_dates` w offers.json — dni, w których scraper zobaczył
    ofertę jako wyróżnioną (main._track_promoted, max 1 wpis/dzień). To metryka
    STANU (ile ofert jest promowanych danego dnia), nie przepływu, więc z bloku
    `_flow_metric` front używa `daily`/`avg`/`rate`/`max_day` — `total` (suma po
    dniach) nie ma tu sensu i nie jest pokazywane.

    Historia zaczyna się w dniu wdrożenia detekcji — wyróżnienia NIE DA SIĘ
    odtworzyć głębiej wstecz (to stan chwilowy na listingu, nie ślad w ofercie),
    więc seria startuje od pierwszego dnia z danymi, nie od RELIABLE_START.

    Druga seria to udział promowanych w rynku (% aktywnych ofert danego dnia),
    liczony na tym samym mianowniku co Indeks (`series`).
    """
    counts = {}
    for o in offers:
        for pd in (o.get('promoted_dates') or []):
            try:
                d = date.fromisoformat(str(pd)[:10])
            except (ValueError, TypeError):
                continue
            counts[d] = counts.get(d, 0) + 1

    if not counts:
        return None

    _, window_days, incomplete = _window(offers, scan_days)
    if not window_days:
        return None
    start = min(counts)
    days = _daily_range(start, window_days[-1])
    if not days:
        return None

    # Dzień liczy się jako zeskanowany, gdy: jest w historii skanów, jakaś oferta
    # ma tam last_seen, albo widzieliśmy tego dnia promowaną ofertę. Reszta = luka
    # (brak skanu), żeby awaria Actions nie wyglądała jak zerowe promowanie.
    # Dni o niepełnym pokryciu wchodzą do tej samej maski: skan widzi wyróżnienia
    # tylko przy przejściu listingu, więc doba z jednym przebiegiem zamiast trzech
    # zaniża licznik tak samo jak Indeks.
    scanned = set(_scan_counts(scan_days)) | _scanned_days(offers) | set(counts)
    missing = incomplete | {d for d in days if d not in scanned}

    metric = _flow_metric(counts, days, skip_days=missing)

    active_by_ms = {ms: val for ms, val in (series or [])}
    share = []
    for d in days:
        ms = _day_ms(d)
        active = active_by_ms.get(ms)
        if d in missing or not active:
            share.append([ms, None])
        else:
            share.append([ms, round(100 * counts.get(d, 0) / active, 1)])

    last_day = next((d for d in reversed(days) if d not in missing), None)
    current = counts.get(last_day, 0) if last_day else None
    current_share = None
    if last_day:
        active = active_by_ms.get(_day_ms(last_day))
        if active:
            current_share = round(100 * counts.get(last_day, 0) / active, 1)

    metric.pop('total', None)
    metric.update({
        'share': share,
        'current': current,
        'current_share': current_share,
        'start': start.isoformat(),
        'start_label': start.strftime('%d.%m.%Y'),
        'days': len(days),
    })
    return metric


def _value_at_or_before(series, target_ms):
    """Ostatnia ZMIERZONA wartość nie później niż `target_ms` (luki pomijamy)."""
    best = None
    for ms, val in series:
        if ms > target_ms:
            break
        if val is not None:
            best = val
    return best


def compute_deltas(series):
    """Zmiany 1D/1M/6M/1Y vs dziś. None gdy nie mamy tak starej historii."""
    measured = [(ms, val) for ms, val in series if val is not None]
    if not measured:
        return {}
    now_ms, current = measured[-1]
    first_ms = measured[0][0]
    now_day = datetime.fromtimestamp(now_ms / 1000).date()
    out = {}
    for label, days in (('1D', 1), ('1M', 30), ('6M', 182), ('1Y', 365)):
        # FIX 2026-09-04: cel liczymy w dniach KALENDARZA, nie przez odjęcie
        # `days * 86_400_000`. Punkty stoją w południe czasu lokalnego, więc po
        # zmianie czasu (25.10) doba ma 23 albo 25 h i cel lądował godzinę przed
        # południem — `_value_at_or_before` brał wtedy dzień wcześniejszy.
        target = _day_ms(now_day - timedelta(days=days))
        if target < first_ms:
            out[label] = None  # brak tak starych danych → front pokaże "—"
            continue
        past = _value_at_or_before(series, target)
        out[label] = (current - past) if past is not None else None
    return out


def generate_trend_data(input_file=None, output_file=None) -> bool:
    """data/offers.json → docs/trend_data.json (dzienna rekonstrukcja)."""
    input_file = Path(input_file or paths.OFFERS_JSON)
    output_file = Path(output_file or paths.DOCS_TREND_JSON)

    print("🔄 Generowanie trend_data.json...")
    with open(input_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    offers = data.get('offers', [])

    scan_counts = load_scan_counts(input_file)
    series = build_series(offers, scan_counts)
    if not series:
        print("⚠️  Brak danych do rekonstrukcji — pomijam trend_data.json")
        return False

    measured = [(ms, val) for ms, val in series if val is not None]
    if not measured:
        print("⚠️  Same luki w serii (brak dni ze skanem) — pomijam trend_data.json")
        return False
    values = [val for _, val in measured]
    current = values[-1]
    mx, mn = max(values), min(values)
    # MAX: pierwsze wystąpienie, MIN: ostatnie (spójnie z SONAR POKOJOWY)
    max_ts = next(ms for ms, val in measured if val == mx)
    min_ts = next(ms for ms, val in reversed(measured) if val == mn)
    last_day = datetime.fromtimestamp(measured[-1][0] / 1000).date()

    out = {
        'generated_at': datetime.now().astimezone().isoformat(),
        'title': TITLE,
        'metric': 'active_daily',
        'unit': UNIT,
        'reliable_start': RELIABLE_START.isoformat(),
        'rate_window_days': FLOW_RATE_WINDOW_DAYS,
        'current': current,
        'max': mx,
        'min': mn,
        'max_ts': max_ts,
        'min_ts': min_ts,
        'last_label': last_day.strftime('%d.%m.%Y'),
        'points': len(series),
        'deltas': compute_deltas(series),
        'series': series,
        'outflow': build_outflow(offers, scan_counts),
        'inflow': build_inflow(offers, scan_counts),
        'bands': build_bands(offers, scan_counts),
        'promoted': build_promoted(offers, series, scan_counts),
    }

    atomic_write_json(output_file, out)
    of = out['outflow'] or {}
    inf = out['inflow'] or {}
    bands = out['bands'] or {}
    gaps = sum(1 for _, val in series if val is None)
    print(f"✅ trend_data.json: {len(series)} dni od {RELIABLE_START} "
          f"do {out['last_label']} ({gaps} dni niepełnych), "
          f"teraz={current}, max={mx}, min={mn}; "
          f"odpływ: łącznie={of.get('total')}, "
          f"śr={of.get('rate')}/dzień (ost. {of.get('rate_days')} dni), "
          f"rekord={of.get('max_day')} ({of.get('max_label')})")
    if inf:
        print(f"   napływ: nowe {inf['new']['rate']}/dzień, "
              f"powroty {inf['react']['rate']}/dzień, "
              f"razem {inf['new_react']['rate']}/dzień")
    if bands:
        fresh = next((v for _, v in reversed(bands['new']) if v is not None), 0)
        recycled = next((v for _, v in reversed(bands['react']) if v is not None), 0)
        total = fresh + recycled
        share = round(100 * recycled / total) if total else 0
        print(f"   pasma dziś: świeże {fresh} + recykling {recycled} "
              f"= {total} ({share}% recyklingu)")
    pr = out['promoted']
    if pr:
        print(f"   ⭐ promowane: teraz={pr.get('current')} ({pr.get('current_share')}% rynku), "
              f"śr={pr.get('rate')}/dzień, rekord={pr.get('max_day')} ({pr.get('max_label')}), "
              f"historia od {pr.get('start_label')}")
    else:
        print("   ⭐ promowane: brak danych (metryka zbiera się od pierwszego skanu po wdrożeniu)")
    return True


if __name__ == '__main__':
    generate_trend_data()

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
from datetime import datetime, date, timedelta
from pathlib import Path

import paths
import reactivation_log
from atomic_json import atomic_write_json

TITLE = "Lublin – mieszkania: wynajem"
UNIT = "ofert"
DAY_MS = 86_400_000

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


def _day_ms(d: date) -> int:
    """Epoch (ms) dla południa danego dnia — punkt ląduje w środku dnia na osi."""
    return int(datetime(d.year, d.month, d.day, 12, 0).timestamp() * 1000)


def _d(iso_string: str) -> date:
    return datetime.fromisoformat(iso_string).date()


def _safe_day(iso_string):
    """ISO → date; None zamiast wyjątku (w bazie trafiają się śmieciowe daty)."""
    try:
        return _d(iso_string)
    except (ValueError, TypeError):
        return None


def _offer_spans(offers):
    """[(oferta, start, end), ...] — okres życia oferty razem z samą ofertą.

    Wersja z ofertą jest potrzebna pasmom (`build_bands`), które muszą zajrzeć
    do historii reaktywacji; `build_spans` zwraca z tego same okresy.
    """
    today = max(
        (d for d in (_safe_day(o.get('last_seen')) for o in offers) if d),
        default=date.today(),
    )
    spans = []
    for o in offers:
        start = _safe_day(o.get('first_seen'))
        last = _safe_day(o.get('last_seen'))
        if start is None or last is None:
            continue
        end = today if o.get('active') else last
        if end < start:
            end = start
        spans.append((o, start, end))
    return spans, today


def build_spans(offers):
    """[(start_date, end_date), ...] — okres życia każdej oferty.

    end = dzień ostatniego skanu dla ofert wciąż aktywnych (ich `last_seen`
    może być nieco w tyle przez inteligentne pomijanie szczegółów),
    inaczej `last_seen`.
    """
    spans, today = _offer_spans(offers)
    return [(start, end) for _, start, end in spans], today


def _days_window(spans, today):
    """Lista dni wykresu: od pierwszego wiarygodnego dnia do ostatniego skanu."""
    start = max(RELIABLE_START, min(s for s, _ in spans))
    days = []
    day = start
    while day <= today:
        days.append(day)
        day += timedelta(days=1)
    return days


def build_series(offers):
    """Dzienna seria [[ms, liczba_aktywnych], ...] od RELIABLE_START do dziś."""
    spans, today = build_spans(offers)
    if not spans:
        return []
    start = max(RELIABLE_START, min(s for s, _ in spans))
    series = []
    day = start
    while day <= today:
        count = sum(1 for s, e in spans if s <= day <= e)
        series.append([_day_ms(day), count])
        day += timedelta(days=1)
    return series


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

    return {
        'daily': daily,
        'avg': avg,
        'total': total,
        'rate': round(total / len(counted), 1) if counted else 0,
        'max_day': mx,
        'max_ts': _day_ms(record_day),
        'max_label': record_day.strftime('%d.%m'),
    }


def build_outflow(offers):
    """Dzienny odpływ ofert (ile zniknęło danego dnia) + średnia krocząca 7 dni.

    „Zniknięcie" = oferta nieaktywna, której `last_seen` przypada danego dnia —
    to ostatni dzień, w którym żyła. Liczymy narastająco tak samo jak Indeks:
    od RELIABLE_START do dziś, dzień po dniu. Druga seria to trailing average
    z 7 dni — wygładza dzienny szum i pokazuje trend nasilenia znikania.
    """
    spans, today = build_spans(offers)
    if not spans:
        return None
    days = _days_window(spans, today)
    start = days[0]

    dep = {}
    for o in offers:
        if o.get('active'):
            continue
        d = _safe_day(o.get('last_seen'))
        if d and d >= start:
            dep[d] = dep.get(d, 0) + 1

    return _flow_metric(dep, days)


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


def build_inflow(offers):
    """Napływ ofert: nowe / reaktywacje / suma — dziennie + średnia 7 dni.

    - `new`   — ogłoszenia widziane pierwszy raz (`first_seen` = ten dzień),
    - `react` — powroty na rynek po realnej nieobecności (`reactivation_log`),
    - `new_react` — suma jednego i drugiego, czyli cały dopływ ofert.

    Dni bez pomiaru powrotów (przed `measured_from`) i dni-artefakty
    (`REACTIVATION_ARTIFACT_DAYS`) idą do serii jako `None` — na wykresie widać
    w tym miejscu przerwę zamiast liczby, której nie umiemy obronić. Suma
    dziedziczy tę maskę: „cały dopływ" bez powrotów byłby po prostu wykresem
    nowych ofert pod cudzą etykietą.
    """
    spans, today = build_spans(offers)
    if not spans:
        return None
    days = _days_window(spans, today)
    window = set(days)

    new_counts, react_counts = {}, {}
    for o in offers:
        first = _safe_day(o.get('first_seen'))
        if first in window:
            new_counts[first] = new_counts.get(first, 0) + 1
        for day in reactivation_log.return_days(
                o, skip_days=REACTIVATION_ARTIFACT_DAYS):
            if day in window:
                react_counts[day] = react_counts.get(day, 0) + 1

    both = {d: new_counts.get(d, 0) + react_counts.get(d, 0)
            for d in set(new_counts) | set(react_counts)}

    since = measured_from(offers)
    unmeasured = {d for d in days if since is None or d < since}
    react_skip = REACTIVATION_ARTIFACT_DAYS | unmeasured

    return {
        'new': _flow_metric(new_counts, days),
        'react': _flow_metric(react_counts, days, react_skip),
        'new_react': _flow_metric(both, days, react_skip),
        'measured_from': since.isoformat() if since else None,
    }


def build_bands(offers):
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
    spans, today = _offer_spans(offers)
    if not spans:
        return None
    since = measured_from(offers)
    if since is None:
        return None
    days = [d for d in _days_window([(s, e) for _, s, e in spans], today)
            if d >= since]
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

    return {
        'new': [[_day_ms(d), v] for d, v in zip(days, fresh)],
        'react': [[_day_ms(d), v] for d, v in zip(days, recycled)],
    }


def _value_at_or_before(series, target_ms):
    best = None
    for ms, val in series:
        if ms <= target_ms:
            best = val
        else:
            break
    return best


def compute_deltas(series):
    """Zmiany 1D/1M/6M/1Y vs dziś. None gdy nie mamy tak starej historii."""
    if not series:
        return {}
    now_ms = series[-1][0]
    current = series[-1][1]
    first_ms = series[0][0]
    out = {}
    for label, days in (('1D', 1), ('1M', 30), ('6M', 182), ('1Y', 365)):
        target = now_ms - days * DAY_MS
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

    series = build_series(offers)
    if not series:
        print("⚠️  Brak danych do rekonstrukcji — pomijam trend_data.json")
        return False

    values = [val for _, val in series]
    current = values[-1]
    mx, mn = max(values), min(values)
    # MAX: pierwsze wystąpienie, MIN: ostatnie (spójnie z SONAR POKOJOWY)
    max_ts = next(ms for ms, val in series if val == mx)
    min_ts = next(ms for ms, val in reversed(series) if val == mn)
    last_day = datetime.fromtimestamp(series[-1][0] / 1000).date()

    out = {
        'generated_at': datetime.now().astimezone().isoformat(),
        'title': TITLE,
        'metric': 'active_daily',
        'unit': UNIT,
        'reliable_start': RELIABLE_START.isoformat(),
        'current': current,
        'max': mx,
        'min': mn,
        'max_ts': max_ts,
        'min_ts': min_ts,
        'last_label': last_day.strftime('%d.%m.%Y'),
        'points': len(series),
        'deltas': compute_deltas(series),
        'series': series,
        'outflow': build_outflow(offers),
        'inflow': build_inflow(offers),
        'bands': build_bands(offers),
    }

    atomic_write_json(output_file, out)
    of = out['outflow'] or {}
    inf = out['inflow'] or {}
    bands = out['bands'] or {}
    print(f"✅ trend_data.json: {len(series)} dni od {RELIABLE_START}, "
          f"teraz={current}, max={mx}, min={mn}; "
          f"odpływ: łącznie={of.get('total')}, śr={of.get('rate')}/dzień, "
          f"rekord={of.get('max_day')} ({of.get('max_label')})")
    if inf:
        print(f"   napływ: nowe {inf['new']['rate']}/dzień, "
              f"powroty {inf['react']['rate']}/dzień, "
              f"razem {inf['new_react']['rate']}/dzień")
    if bands:
        fresh, recycled = bands['new'][-1][1], bands['react'][-1][1]
        total = fresh + recycled
        share = round(100 * recycled / total) if total else 0
        print(f"   pasma dziś: świeże {fresh} + recykling {recycled} "
              f"= {total} ({share}% recyklingu)")
    return True


if __name__ == '__main__':
    generate_trend_data()

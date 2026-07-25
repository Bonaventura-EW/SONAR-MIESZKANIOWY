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
from atomic_json import atomic_write_json

TITLE = "Lublin – mieszkania: wynajem"
UNIT = "ofert"
DAY_MS = 86_400_000

# Pierwszy wiarygodny dzień (po naprawach parsera adresów z 16.05.2026).
# Wszystko wcześniej to artefakt zbierania danych, nie obraz rynku.
RELIABLE_START = date(2026, 5, 16)


def _day_ms(d: date) -> int:
    """Epoch (ms) dla południa danego dnia — punkt ląduje w środku dnia na osi."""
    return int(datetime(d.year, d.month, d.day, 12, 0).timestamp() * 1000)


def _d(iso_string: str) -> date:
    return datetime.fromisoformat(iso_string).date()


def build_spans(offers):
    """[(start_date, end_date), ...] — okres życia każdej oferty.

    end = dzień ostatniego skanu dla ofert wciąż aktywnych (ich `last_seen`
    może być nieco w tyle przez inteligentne pomijanie szczegółów),
    inaczej `last_seen`.
    """
    today = max(
        (_d(o['last_seen']) for o in offers if o.get('last_seen')),
        default=date.today(),
    )
    spans = []
    for o in offers:
        if not o.get('first_seen') or not o.get('last_seen'):
            continue
        try:
            start = _d(o['first_seen'])
            end = today if o.get('active') else _d(o['last_seen'])
        except (ValueError, TypeError):
            continue
        if end < start:
            end = start
        spans.append((start, end))
    return spans, today


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
    start = max(RELIABLE_START, min(s for s, _ in spans))

    dep = {}
    for o in offers:
        if o.get('active') or not o.get('last_seen'):
            continue
        try:
            d = _d(o['last_seen'])
        except (ValueError, TypeError):
            continue
        if d >= start:
            dep[d] = dep.get(d, 0) + 1

    days = []
    day = start
    while day <= today:
        days.append(day)
        day += timedelta(days=1)

    vals = [dep.get(d, 0) for d in days]
    daily = [[_day_ms(d), v] for d, v in zip(days, vals)]

    avg = []
    for i, d in enumerate(days):
        window = vals[max(0, i - 6):i + 1]
        avg.append([_day_ms(d), round(sum(window) / len(window), 1)])

    total = sum(vals)
    ndays = len(days)
    mx = max(vals) if vals else 0
    # dzień rekordu: ostatnie (najświeższe) wystąpienie maksimum
    max_idx = max((i for i, v in enumerate(vals) if v == mx), default=0)
    max_day_date = days[max_idx] if days else start

    return {
        'daily': daily,
        'avg': avg,
        'total': total,
        'rate': round(total / ndays, 1) if ndays else 0,
        'max_day': mx,
        'max_ts': _day_ms(max_day_date),
        'max_label': max_day_date.strftime('%d.%m'),
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
    }

    atomic_write_json(output_file, out)
    of = out['outflow'] or {}
    print(f"✅ trend_data.json: {len(series)} dni od {RELIABLE_START}, "
          f"teraz={current}, max={mx}, min={mn}; "
          f"odpływ: łącznie={of.get('total')}, śr={of.get('rate')}/dzień, "
          f"rekord={of.get('max_day')} ({of.get('max_label')})")
    return True


if __name__ == '__main__':
    generate_trend_data()

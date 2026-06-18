#!/usr/bin/env python3
"""Generator docs/area_price_data.json — dane podstrony "Analiza cen wg metrażu".

Analizuje treść WSZYSTKICH ofert (aktywne + historia) z data/offers.json:
wyciąga metraż (m²), liczbę pokoi i dzielnicę (patrz area_parser), liczy cenę za
m², przedziały cenowe wg metrażu, statystyki dzielnic, mapę cieplną
dzielnica×metraż, korelację powierzchnia-cena, trend zł/m² w czasie i rozkłady.

Uruchom: `cd src && python area_price_generator.py`
W pipeline odpalany po main.py (workflow scanner.yml), commitowany do repo.
"""

import json
import math
import random
import statistics
from collections import defaultdict
from datetime import datetime

from area_parser import extract_area, extract_rooms, extract_district
from atomic_json import atomic_write_json
import paths

# Przedziały metrażu (lewostronnie domknięte: [min, max)). Kolor = gradient
# zielony→czerwony spójny z mapą (małe mieszkania = drogi metr = czerwień).
AREA_BRACKETS = [
    (0, 25, 'do 25 m²', '#10b981'),
    (25, 35, '25–35 m²', '#22c55e'),
    (35, 45, '35–45 m²', '#84cc16'),
    (45, 55, '45–55 m²', '#eab308'),
    (55, 70, '55–70 m²', '#f97316'),
    (70, 90, '70–90 m²', '#ef4444'),
    (90, 10_000, '90 m²+', '#dc2626'),
]

PPM_BIN_WIDTH = 10        # szerokość kosza histogramu zł/m²
PPM_HIST_MAX = 120        # ostatni kosz to "120+"
SCATTER_MAX_POINTS = 500  # próbka do wykresu rozrzutu (czytelność + rozmiar pliku)
MIN_DISTRICT_OFFERS = 5   # dzielnica poniżej progu jest zbyt szczupła statystycznie
MIN_HEATMAP_CELL = 2      # komórka heatmapy wymaga min. tylu ofert


def _percentile(values, q):
    """Percentyl q∈[0,1] metodą interpolacji liniowej (jak numpy 'linear')."""
    xs = sorted(values)
    if not xs:
        return None
    k = (len(xs) - 1) * q
    f, c = math.floor(k), math.ceil(k)
    if f == c:
        return xs[int(k)]
    return xs[f] * (c - k) + xs[c] * (k - f)


def _med(values):
    return round(statistics.median(values)) if values else None


def build_stats(offers):
    """Czysta agregacja (bez I/O) — zwraca słownik gotowy do serializacji."""
    records = []
    for o in offers:
        price = (o.get('price') or {}).get('current')
        area = extract_area(o)
        if not price or not area:
            continue
        records.append({
            'price': price,
            'area': area,
            'ppm': price / area,
            'rooms': extract_rooms(o),
            'district': extract_district(o),
            'first_seen': o.get('first_seen'),
        })

    overall = _overall(records)
    return {
        'meta': {
            'generated': datetime.now().isoformat(timespec='seconds'),
            'total_offers': len(offers),
            'analyzed': len(records),
            'coverage_pct': round(100 * len(records) / len(offers)) if offers else 0,
        },
        'overall': overall,
        'area_brackets': _brackets(records),
        'ppm_hist': _ppm_hist(records),
        'scatter': _scatter(records),
        'districts': _districts(records),
        'heatmap': _heatmap(records),
        'trend': _trend(records),
        'rooms': _rooms(records),
    }


def _overall(records):
    if not records:
        return {'count': 0}
    prices = [r['price'] for r in records]
    areas = [r['area'] for r in records]
    ppms = [r['ppm'] for r in records]
    return {
        'count': len(records),
        'median_price': _med(prices),
        'median_area': round(statistics.median(areas), 1),
        'median_ppm': round(statistics.median(ppms), 1),
        'mean_ppm': round(statistics.mean(ppms), 1),
        'min_ppm': round(min(ppms), 1),
        'max_ppm': round(max(ppms), 1),
        'p25_ppm': round(_percentile(ppms, 0.25), 1),
        'p75_ppm': round(_percentile(ppms, 0.75), 1),
        'p10_price': round(_percentile(prices, 0.10)),
        'p90_price': round(_percentile(prices, 0.90)),
    }


def _brackets(records):
    out = []
    for lo, hi, label, color in AREA_BRACKETS:
        grp = [r for r in records if lo <= r['area'] < hi]
        if not grp:
            continue
        prices = [r['price'] for r in grp]
        ppms = [r['ppm'] for r in grp]
        out.append({
            'label': label, 'min': lo, 'max': hi, 'color': color,
            'count': len(grp),
            'median_price': _med(prices),
            'median_ppm': round(statistics.median(ppms), 1),
            'p25_price': round(_percentile(prices, 0.25)),
            'p75_price': round(_percentile(prices, 0.75)),
            'min_price': min(prices), 'max_price': max(prices),
        })
    return out


def _ppm_hist(records):
    bins = list(range(0, PPM_HIST_MAX + PPM_BIN_WIDTH, PPM_BIN_WIDTH))
    counts = [0] * len(bins)
    for r in records:
        idx = min(int(r['ppm'] // PPM_BIN_WIDTH), len(bins) - 1)
        counts[idx] += 1
    labels = [f"{b}-{b + PPM_BIN_WIDTH}" for b in bins[:-1]] + [f"{bins[-1]}+"]
    return {'labels': labels, 'counts': counts}


def _scatter(records):
    sample = records
    if len(records) > SCATTER_MAX_POINTS:
        rng = random.Random(7)  # deterministyczne — stabilny diff pliku
        sample = rng.sample(records, SCATTER_MAX_POINTS)
    return [[round(r['area'], 1), r['price']] for r in sample]


def _districts(records):
    by_district = defaultdict(list)
    for r in records:
        if r['district']:
            by_district[r['district']].append(r)
    out = []
    for name, grp in by_district.items():
        if len(grp) < MIN_DISTRICT_OFFERS:
            continue
        out.append({
            'name': name,
            'count': len(grp),
            'median_price': _med([r['price'] for r in grp]),
            'median_area': round(statistics.median([r['area'] for r in grp]), 1),
            'median_ppm': round(statistics.median([r['ppm'] for r in grp]), 1),
        })
    out.sort(key=lambda d: -d['median_ppm'])
    return out


def _heatmap(records):
    """Mediana zł/m² w przecięciu (8 najliczniejszych dzielnic) × przedział metrażu."""
    by_district = defaultdict(list)
    for r in records:
        if r['district']:
            by_district[r['district']].append(r)
    top = sorted(by_district, key=lambda d: -len(by_district[d]))[:8]
    brackets = _brackets(records)
    matrix = []
    for dn in top:
        row = []
        for b in brackets:
            cell = [r['ppm'] for r in by_district[dn] if b['min'] <= r['area'] < b['max']]
            row.append(round(statistics.median(cell), 1) if len(cell) >= MIN_HEATMAP_CELL else None)
        matrix.append(row)
    return {'districts': top, 'brackets': [b['label'] for b in brackets], 'ppm': matrix}


def _trend(records):
    by_month = defaultdict(list)
    for r in records:
        fs = r.get('first_seen')
        if fs and len(fs) >= 7:
            by_month[fs[:7]].append(r)
    return [{
        'month': m,
        'count': len(by_month[m]),
        'median_price': _med([r['price'] for r in by_month[m]]),
        'median_ppm': round(statistics.median([r['ppm'] for r in by_month[m]]), 1),
    } for m in sorted(by_month)]


def _rooms(records):
    by_rooms = defaultdict(list)
    for r in records:
        if r['rooms']:
            by_rooms[r['rooms']].append(r)
    return [{
        'rooms': k,
        'count': len(by_rooms[k]),
        'median_price': _med([r['price'] for r in by_rooms[k]]),
        'median_area': round(statistics.median([r['area'] for r in by_rooms[k]]), 1),
        'median_ppm': round(statistics.median([r['ppm'] for r in by_rooms[k]]), 1),
    } for k in sorted(by_rooms)]


def generate(input_file=paths.OFFERS_JSON, output_file=paths.DOCS_AREA_PRICE_JSON):
    print("🔄 Generowanie area_price_data.json...")
    with open(input_file, 'r', encoding='utf-8') as f:
        offers = json.load(f).get('offers', [])
    print(f"📥 Wczytano {len(offers)} ofert")

    stats = build_stats(offers)
    atomic_write_json(output_file, stats)

    m, o = stats['meta'], stats['overall']
    print(f"✅ Zapisano {output_file}")
    print(f"   Przeanalizowano {m['analyzed']}/{m['total_offers']} ofert "
          f"(metraż w {m['coverage_pct']}%)")
    if o.get('count'):
        print(f"   Mediana: {o['median_price']} zł · {o['median_ppm']} zł/m² · {o['median_area']} m²")
        print(f"   Przedziałów: {len(stats['area_brackets'])} · dzielnic: {len(stats['districts'])}")
    return stats


if __name__ == '__main__':
    generate()

"""Testy agregacji statystyk cena/metraż (area_price_generator.build_stats)."""

import area_price_generator as gen


def _offer(price, desc, first_seen='2026-05-01T10:00:00+02:00'):
    return {'price': {'current': price}, 'description': desc, 'first_seen': first_seen}


def test_empty_input():
    stats = gen.build_stats([])
    assert stats['overall'] == {'count': 0}
    assert stats['meta']['coverage_pct'] == 0
    assert stats['area_brackets'] == []


def test_skips_offers_without_area_or_price():
    offers = [
        _offer(2000, 'mieszkanie bez metrażu'),   # brak m² -> pominięte
        {'price': {}, 'description': '40 m2'},     # brak ceny -> pominięte
        _offer(2000, 'mieszkanie 40 m2'),          # OK
    ]
    stats = gen.build_stats(offers)
    assert stats['overall']['count'] == 1
    assert stats['meta']['total_offers'] == 3
    assert stats['meta']['analyzed'] == 1


def test_ppm_and_medians():
    offers = [_offer(2000, 'mieszkanie 40 m2'), _offer(3000, 'mieszkanie 60 m2')]
    o = gen.build_stats(offers)['overall']
    assert o['count'] == 2
    assert o['median_price'] == 2500            # mediana 2000/3000
    assert o['median_area'] == 50.0             # mediana 40/60
    # zł/m²: 2000/40=50, 3000/60=50 -> mediana 50
    assert o['median_ppm'] == 50.0


def test_brackets_assign_by_area():
    offers = [
        _offer(1800, 'kawalerka 22 m2'),   # do 25
        _offer(2200, 'mieszkanie 40 m2'),  # 35–45
        _offer(2600, 'mieszkanie 60 m2'),  # 55–70
    ]
    brackets = {b['label']: b for b in gen.build_stats(offers)['area_brackets']}
    assert brackets['do 25 m²']['count'] == 1
    assert brackets['35–45 m²']['count'] == 1
    assert brackets['55–70 m²']['count'] == 1


def test_bracket_boundary_is_left_closed():
    # 45 należy do 45–55, nie do 35–45 (przedziały [min, max)).
    offers = [_offer(2400, 'mieszkanie 45 m2')]
    brackets = {b['label']: b for b in gen.build_stats(offers)['area_brackets']}
    assert '45–55 m²' in brackets
    assert '35–45 m²' not in brackets


def test_districts_threshold():
    # 4 oferty z dzielnicy < próg (5) -> dzielnica pominięta w zestawieniu.
    offers = [_offer(2000, f'mieszkanie 40 m2 na LSM, oferta {i}') for i in range(4)]
    assert gen.build_stats(offers)['districts'] == []
    # 5 ofert -> dzielnica się pojawia.
    offers.append(_offer(2000, 'mieszkanie 40 m2 na LSM, oferta 5'))
    names = [d['name'] for d in gen.build_stats(offers)['districts']]
    assert 'LSM' in names


def test_trend_grouped_by_month():
    offers = [
        _offer(2000, 'mieszkanie 40 m2', '2026-04-10T10:00:00+02:00'),
        _offer(2200, 'mieszkanie 44 m2', '2026-05-10T10:00:00+02:00'),
    ]
    months = [t['month'] for t in gen.build_stats(offers)['trend']]
    assert months == ['2026-04', '2026-05']


def test_scatter_capped():
    offers = [_offer(2000, 'mieszkanie 40 m2') for _ in range(gen.SCATTER_MAX_POINTS + 50)]
    assert len(gen.build_stats(offers)['scatter']) == gen.SCATTER_MAX_POINTS


# ── Okazje (ranking rabatu vs mediana grupy) ─────────────────────────────────

def _active(price, desc, title='Mieszkanie do wynajęcia', oid=None, url='https://olx.pl/x'):
    return {'price': {'current': price}, 'description': desc, 'title': title,
            'active': True, 'id': oid or title, 'url': url,
            'first_seen': '2026-05-01T10:00:00+02:00'}


def test_okazje_ignores_inactive_offers():
    # _offer(...) nie ma active=True -> nie trafia do rankingu okazji.
    k = gen.build_stats([_offer(2000, 'mieszkanie 40 m2')])['okazje']
    assert k['analyzed'] == 0
    assert k['count'] == 0
    assert k['offers'] == []


def test_okazje_discount_vs_group_median():
    # 8 kawalerek ~55 zł/m² + jedna wyraźnie tańsza -> ta jedna to okazja.
    offers = [_active(2200, 'kawalerka 40 m2', title=f'Kawalerka {i}') for i in range(8)]
    offers.append(_active(1600, 'kawalerka 40 m2', title='Tania kawalerka'))
    k = gen.build_stats(offers)['okazje']
    top = k['offers'][0]
    assert top['title'] == 'Tania kawalerka'
    assert top['discount_pct'] > 0          # poniżej mediany grupy
    assert top['est_savings'] > 0
    assert top['group'].startswith('1-pokojowe')  # kaskada spadła na pokoje/miasto
    assert top['group_n'] >= gen.OKAZJE_ROOMS_MIN
    assert k['count'] >= 1


def test_okazje_atypical_by_title_excluded_from_medians():
    # "Pokój w mieszkaniu" tania -> nietypowa, nie zaniża mediany typowych.
    offers = [_active(2200, 'mieszkanie 40 m2', title=f'Mieszkanie {i}') for i in range(8)]
    offers.append(_active(600, 'pokój 40 m2', title='Pokój w mieszkaniu 4 pokojowym'))
    k = gen.build_stats(offers)['okazje']
    atyp = [o for o in k['offers'] if o['atypical']]
    assert len(atyp) == 1
    assert 'pokój' in atyp[0]['atypical_reason'].lower()
    assert k['atypical_count'] == 1
    # mediana miasta ~55 (typowe), nie ściągnięta przez pokój (15 zł/m²)
    assert k['city_median_ppm'] > 40


def test_okazje_atypical_by_price_threshold():
    offers = [_active(2200, 'mieszkanie 40 m2', title=f'Mieszkanie {i}') for i in range(8)]
    # 800/40 = 20 zł/m² < 55% * ~55 -> nietypowa mimo neutralnego tytułu.
    offers.append(_active(800, 'mieszkanie 40 m2', title='Super tanie mieszkanie'))
    k = gen.build_stats(offers)['okazje']
    cheap = [o for o in k['offers'] if o['title'] == 'Super tanie mieszkanie']
    assert cheap and cheap[0]['atypical']
    assert 'mediany miasta' in cheap[0]['atypical_reason']


def test_okazje_city_fallback_is_weak():
    # Bez dzielnicy i bez rozpoznanych pokoi -> ostatni szczebel = całe miasto, weak.
    offers = [_active(2000 + i * 50, 'lokal 40 m2', title=f'Lokal {i}') for i in range(6)]
    k = gen.build_stats(offers)['okazje']
    assert all(o['group'] == 'całe miasto' for o in k['offers'])
    assert all(o['weak'] for o in k['offers'])

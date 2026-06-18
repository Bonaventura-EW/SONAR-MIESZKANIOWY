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

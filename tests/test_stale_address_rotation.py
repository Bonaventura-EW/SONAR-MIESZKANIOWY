"""Testy rotacji re-fetchu dla ofert z zamrożonym adresem (scraper._promote_stale_imprecise).

Propagacja z SONAR-POKOJOWY (manifest 2026-09-07-address-precision-upgrade,
issue #50): inteligentne skanowanie pomija pobranie szczegółów, gdy cena się
nie zmieniła, więc oferta z markerem 'street' (brak numeru / fallback
geokodera) nigdy nie dostaje szansy na doprecyzowanie, dopóki cena stoi
w miejscu. Rotacja wymusza realny re-fetch dla najstarszych takich rekordów.
"""

from datetime import datetime, timedelta, timezone

from scraper import OLXScraper


def _skip_item(offer_id, precision, age_days=None, coords=True):
    """Buduje wpis 'offers_to_skip' z ofertą o danej precyzji adresu i wieku
    ostatniego realnego pobrania (details_fetched_at)."""
    details_fetched_at = None
    if age_days is not None:
        details_fetched_at = (
            datetime.now(timezone.utc) - timedelta(days=age_days)
        ).isoformat()
    existing = {
        'address': {'precision': precision, 'coords': {'lat': 1, 'lon': 2}} if coords else {'precision': precision},
        'coordinates': {'lat': 1, 'lon': 2} if coords else None,
        'was_active': True,
        'details_fetched_at': details_fetched_at,
    }
    return {
        'offer': {'title': f'oferta {offer_id}', 'url': f'https://www.olx.pl/d/oferta/x-{offer_id}.html'},
        'existing': existing,
        'reason': 'same_price',
    }


def test_promotes_only_street_precision_past_min_age():
    scraper = OLXScraper()
    offers_to_skip = [
        _skip_item('street-old', 'street', age_days=10),   # candidate
        _skip_item('exact-old', 'exact', age_days=10),     # ma numer — nic do zyskania
        _skip_item('street-fresh', 'street', age_days=1),  # za świeże (<MIN_AGE_DAYS)
        _skip_item('none-old', 'none', age_days=10),       # brak adresu do doprecyzowania
    ]
    offers_to_fetch = []

    remaining = scraper._promote_stale_imprecise(offers_to_skip, offers_to_fetch)

    promoted_titles = {item['offer']['title'] for item in offers_to_fetch}
    remaining_titles = {item['offer']['title'] for item in remaining}

    assert promoted_titles == {'oferta street-old'}
    assert remaining_titles == {'oferta exact-old', 'oferta street-fresh', 'oferta none-old'}
    assert scraper.stats['fetched_stale_address'] == 1
    assert scraper.stats['skipped_same_price'] == -1


def test_missing_details_fetched_at_counts_as_oldest():
    scraper = OLXScraper()
    scraper.STALE_REFRESH_BUDGET = 1
    offers_to_skip = [
        _skip_item('recent', 'street', age_days=10),
        _skip_item('never-fetched', 'street', age_days=None),  # brak znacznika = najstarsze
    ]
    offers_to_fetch = []

    scraper._promote_stale_imprecise(offers_to_skip, offers_to_fetch)

    assert [item['offer']['title'] for item in offers_to_fetch] == ['oferta never-fetched']


def test_promoted_offer_carries_cache_safety_net():
    """Świeży parsing może nie znaleźć adresu wcale — cache musi jechać z ofertą,
    inaczej rekord poleciałby do warstwy 'bez lokacji' mimo że wciąż wisi na OLX."""
    scraper = OLXScraper()
    offers_to_skip = [_skip_item('street-old', 'street', age_days=10)]
    offers_to_fetch = []

    scraper._promote_stale_imprecise(offers_to_skip, offers_to_fetch)

    promoted = offers_to_fetch[0]['offer']
    assert promoted['cached_address']['precision'] == 'street'
    assert promoted['cached_coordinates'] == {'lat': 1, 'lon': 2}
    assert 'skipped' not in promoted  # to teraz realny fetch, nie skip


def test_respects_budget():
    scraper = OLXScraper()
    scraper.STALE_REFRESH_BUDGET = 2
    offers_to_skip = [_skip_item(f'street-{i}', 'street', age_days=10 + i) for i in range(5)]
    offers_to_fetch = []

    remaining = scraper._promote_stale_imprecise(offers_to_skip, offers_to_fetch)

    assert len(offers_to_fetch) == 2
    assert len(remaining) == 3
    assert scraper.stats['fetched_stale_address'] == 2


def test_empty_skip_list_is_noop():
    scraper = OLXScraper()
    assert scraper._promote_stale_imprecise([], []) == []
    assert scraper.stats['fetched_stale_address'] == 0

"""Testy sprzątania cache geokodera (FIX 2026-08-07).

Cache karmi whitelistę `_known_streets` w parserze, więc śmieć raz zgeokodowany
uwiarygadnia kolejne takie parsowania. Sprzątanie musi być jednak bezpieczne:
nie wolno ruszyć klucza, na którym stoi jakakolwiek pinezka.
"""

from clean_geocoding_cache import find_junk_keys

STREET_FORMS = {'lipowa', 'lipowej', 'narutowicza', 'zana'}


def _offer(full, street=None):
    return {'address': {'full': full, 'street': street if street is not None else full}}


def test_usuwa_smieci_nieuzywane_przez_oferty():
    cache = {'pod nr 60': {}, 'Duze nowoczesne 2': {}, 'Lipowa 10': {}}
    junk = find_junk_keys(cache, [], STREET_FORMS)
    assert set(junk) == {'pod nr 60', 'Duze nowoczesne 2'}


def test_nie_rusza_klucza_uzywanego_przez_oferte():
    """Klucz, na którym stoi pinezka, zostaje — nawet jeśli to śmieć."""
    cache = {'Wolne 1': {}}
    junk = find_junk_keys(cache, [_offer('Wolne 1', 'Wolne')], STREET_FORMS)
    assert junk == []


def test_nie_rusza_klucza_uzywanego_jako_sama_ulica():
    cache = {'Wolne': {}}
    junk = find_junk_keys(cache, [_offer('Wolne 3', 'Wolne')], STREET_FORMS)
    assert junk == []


def test_zostawia_realne_ulice_takze_w_odmianie():
    cache = {'Lipowej 14': {}, 'Lipowa': {}, 'Narutowicza 38': {}}
    assert find_junk_keys(cache, [], STREET_FORMS) == []


def test_brak_whitelisty_nie_kasuje_wszystkiego():
    """Pusta lista ulic = każdy klucz wyglądałby na śmieć; CLI przerywa wcześniej,
    ale sama funkcja też nie może być używana z pustym zbiorem bez świadomości."""
    cache = {'Lipowa 10': {}}
    assert find_junk_keys(cache, [], set()) == ['Lipowa 10']

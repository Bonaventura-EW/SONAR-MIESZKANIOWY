"""Testy ekstrakcji metrażu / pokoi / dzielnicy z treści ogłoszeń."""

from area_parser import extract_area, extract_rooms, extract_district


# --- metraż -----------------------------------------------------------------

def test_area_basic_m2():
    assert extract_area({'description': 'mieszkanie 47m² po remoncie'}) == 47.0


def test_area_decimal_comma():
    assert extract_area({'description': 'Kawalerka 28,5 m2 w centrum'}) == 28.5


def test_area_words_metrow_kwadratowych():
    assert extract_area({'description': 'pow. 62 metrów kwadratowych'}) == 62.0


def test_area_mkw():
    assert extract_area({'description': 'do wynajęcia 53 mkw'}) == 53.0


def test_area_requires_unit_not_random_number():
    # Sama liczba bez jednostki m² nie może być metrażem (cena, telefon).
    assert extract_area({'description': 'cena 2000 zł, tel 530123456'}) is None


def test_area_out_of_range_rejected():
    assert extract_area({'description': 'ogromne 999 m2'}) is None
    assert extract_area({'description': 'maleńkie 3 m2'}) is None


def test_area_first_match_wins():
    # Pierwsza wzmianka = metraż mieszkania, kolejne (piwnica) pomijane.
    assert extract_area({'description': 'mieszkanie 45 m2, piwnica 6 m2'}) == 45.0


def test_area_missing_description():
    assert extract_area({}) is None


# --- pokoje -----------------------------------------------------------------

def test_rooms_digit_pok():
    assert extract_rooms({'description': '2-pokojowe mieszkanie'}) == 2
    assert extract_rooms({'description': 'przestronne 3 pokoje'}) == 3


def test_rooms_kawalerka_is_one():
    assert extract_rooms({'description': 'przytulna kawalerka'}) == 1


def test_rooms_none_when_unknown():
    assert extract_rooms({'description': 'mieszkanie po remoncie'}) is None


# --- dzielnica --------------------------------------------------------------

def test_district_from_description():
    assert extract_district({'description': 'mieszkanie na LSM, blisko parku'}) == 'LSM'


def test_district_from_address():
    assert extract_district({'address': {'full': 'Czechów Północny'}}) == 'Czechów'


def test_district_priority_specific_over_generic():
    # "Stare Miasto" ma wygrać, mimo że tekst zawiera też ogólniejsze słowa.
    assert extract_district({'description': 'Stare Miasto, klimatyczna kamienica'}) == 'Stare Miasto'


def test_district_none_when_absent():
    assert extract_district({'description': 'spokojna zielona okolica'}) is None

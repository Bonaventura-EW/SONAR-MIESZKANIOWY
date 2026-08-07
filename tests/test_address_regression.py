"""Ochrona przed regresją parsera adresów (FIX 2026-08-06).

Dwie warstwy:

1. **Korpus złoty** (`data_address_corpus.json`) — 120 realnych opisów ofert
   z bazy i adresy, jakie parser z nich wyciąga. Każda przyszła zmiana, która
   zgubi adres albo go przekręci, wywali ten test. To jest bezpiecznik przed
   „poprawką", która po cichu wycina ogłoszenia ze strony: oferta bez adresu
   nie trafia na mapę w ogóle (`main._process_offer` → None).

2. **Przypadki fałszywej precyzji** — numery, które parser dorabiał z innego
   zdania („2-pokojowe" → „Zana 2", „34 m2" → „Nałęczowska 34"). Audyt mapy
   z 2026-08-06 znalazł 51 takich ofert na 322 z „dokładnym" adresem.
"""

import json
from pathlib import Path

import pytest

from address_parser import AddressParser

CORPUS = json.loads((Path(__file__).parent / 'data_address_corpus.json').read_text(encoding='utf-8'))


@pytest.fixture(scope="module")
def parser():
    return AddressParser()


def test_corpus_nie_gubi_adresow(parser):
    """Żaden adres z korpusu nie może zniknąć — to gwarancja, że zmiana parsera
    nie zacznie wycinać ofert ze strony."""
    lost = []
    for case in CORPUS['cases']:
        if parser.extract_address(case['text']) is None:
            lost.append((case['id'], case['full']))
    assert not lost, f"Parser przestał rozpoznawać adres w {len(lost)} ofertach: {lost[:5]}"


def test_corpus_nie_zmienia_adresow(parser):
    """Adresy z korpusu mają zostać takie same (co do treści i flagi has_number)."""
    changed = []
    for case in CORPUS['cases']:
        result = parser.extract_address(case['text'])
        if result and (result['full'] != case['full'] or result['has_number'] != case['has_number']):
            changed.append((case['full'], result['full'], case['has_number'], result['has_number']))
    assert not changed, f"Zmienił się wynik dla {len(changed)} ofert: {changed[:5]}"


@pytest.mark.parametrize("text,expected_full", [
    # Numer z liczby pokoi — najczęstsze źródło zmyślonej precyzji
    ("Mieszkanie 2 pokojowe do wynajęcia ul. ZANA Lublin", "Zana"),
    ("Mieszkanie 2-pokojowe, Kalinowszczyzna, ul. Kustronia Mieszkanie 2 pokojowe", "Kustronia"),
    ("3-pokojowe mieszkanie do wynajęcia, blisko UM, ul. Hirszfelda Lublin", "Hirszfelda"),
    # Numer z metrażu
    ("Studio 34 m2 ul. Nałęczowska Studio 34 m2", "Nałęczowska"),
    ("Kawalerka 20 m2 ul. Chopina Kawalerka 20 m2 Lublin", "Chopina"),
])
def test_nie_dorabia_numeru_z_innego_zdania(parser, text, expected_full):
    """Numer stojący za odciętym słowem-śmieciem nie należy do adresu."""
    result = parser.extract_address(text)
    assert result is not None, f"Zgubiono ulicę w: {text!r}"
    assert result['full'] == expected_full
    assert result['has_number'] is False
    assert result['number'] is None


@pytest.mark.parametrize("text,expected_full", [
    ("ul. Lipowa 10, blisko UMCS", "Lipowa 10"),
    ("Mieszkanie przy ul. Narutowicza 38", "Narutowicza 38"),
    ("Aleje Racławickie 12/2", "Aleje Racławickie 12/2"),
])
def test_prawdziwy_numer_zostaje(parser, text, expected_full):
    """Numer stojący TUŻ przy nazwie ulicy ma zostać nienaruszony."""
    result = parser.extract_address(text)
    assert result is not None
    assert result['full'] == expected_full
    assert result['has_number'] is True


@pytest.mark.parametrize("text", [
    "Mieszkanie 55m przy ul. Wileńskiej",
    "Kawalerka na ul. Granicznej 40m2",
])
def test_metraz_nie_jest_numerem_domu(parser, text):
    """„55m"/„40m2" to metry kwadratowe — w adresie 'm' znaczy 'mieszkanie'."""
    result = parser.extract_address(text)
    if result is not None:
        assert result['has_number'] is False, f"Metraż wzięty za numer domu: {result['full']}"


def test_wybor_ulicy_z_whitelisty_jest_deterministyczny():
    """Remis długości nazw nie może zależeć od kolejności iteracji po zbiorze.

    FIX 2026-08-06: `extract_from_whitelist` (trzeci fallback `extract_address`)
    iteruje po zbiorze `_known_streets`, więc przy dwóch znanych ulicach o nazwach
    tej samej długości zwycięzcę wybierał PYTHONHASHSEED — ten sam opis dawał raz
    „Wrotków", raz „Fulmana", i pinezka skakała między skanami.
    """
    probe = AddressParser()
    probe._known_streets = {'fulmana', 'wrotków', 'spokojnej', 'stokrotka'}
    text = 'Mieszkanie Lublin Wrotków blisko ulicy Fulmana'

    results = {probe.extract_from_whitelist(text)['full'] for _ in range(20)}
    assert len(results) == 1, f"Parser zwraca różne ulice dla tego samego tekstu: {results}"
    # Tie-break: wygrywa nazwa stojąca wcześniej w tekście (tytuł jest na początku)
    assert results == {'Wrotków'}


@pytest.mark.parametrize("text,expected_full", [
    # Metraż i kod pocztowy po przecinku
    ("Kawalerka na ul. Skibińskiej, 20 m, po remoncie", "Skibińskiej"),
    ("Mieszkanie, Lublin, centrum, ul. Chopina, 50 m2, do wynajęcia", "Chopina"),
    ("Lokalizacja: Wieniawa ul. Legionowa, 20-053 Lublin", "Legionowa"),
    # Liczba pokoi i czas dojścia po przecinku
    ("Wynajmę Lublin, os. Nałkowskich, 3 oddzielne pokoje", "Osiedle Nałkowskich"),
    ("Mieszkanie na ul. Filaretów, 2 pokoje i kuchnia", "Filaretów"),
])
def test_przecinek_nie_lapie_numeru(parser, text, expected_full):
    """Przecinek kończy człon zdania — to, co po nim stoi, nie jest numerem domu.

    Sprawdzone 2026-08-07 na całej aktywnej bazie: dopuszczenie przecinka w
    `ADDRESS_PATTERN` dało 7 nowych numerów i wszystkie 7 było fałszywych
    (metraż, kod pocztowy „20-053", „10 min. do UMCS", liczba pokoi).
    """
    result = parser.extract_address(text)
    assert result is not None, f"Zgubiono ulicę w: {text!r}"
    assert result['has_number'] is False, f"Wzięto liczbę po przecinku za numer domu: {result['full']}"
    assert result['full'] == expected_full

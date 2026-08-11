"""Testy migracji adresów zapisanych starym parserem (FIX 2026-08-06).

Oferty nieaktywne nie są odwiedzane przez scraper, więc bez tej migracji
zostałyby ze zmyślonym numerem domu na zawsze — a wchodzą do mapy historycznej
i do analiz cen po adresach.
"""

import json

import pytest

from address_migration import (ADDRESS_PARSER_VERSION, MAX_RETRACTION_RATIO,
                               MIN_OFFERS_FOR_RATIO_GUARD, drop_rejected_labels,
                               retract_fake_numbers)
from main import SonarMieszkaniowy

# Opis, z którego stary parser zrobił „Zana 2" (numer to liczba pokoi)
FAKE_NUMBER_TEXT = 'Mieszkanie 2 pokojowe do wynajęcia ul. ZANA Lublin, umeblowane'
# Opis z prawdziwym numerem tuż przy nazwie ulicy
REAL_NUMBER_TEXT = 'Do wynajęcia mieszkanie przy ul. Lipowa 10 w Lublinie'


def _offer(full, street, number, description, active=False, coords=None):
    return {
        'id': f'x-CID3-ID{full}', 'active': active, 'description': description,
        'address': {'full': full, 'street': street, 'number': number,
                    'has_number': bool(number),
                    **({'coords': coords} if coords else {})},
    }


class TestRetractFakeNumbers:
    def test_wycofuje_numer_w_nieaktywnej_ofercie(self):
        offers = [_offer('Zana 2', 'Zana', '2', FAKE_NUMBER_TEXT, active=False,
                         coords={'lat': 51.24, 'lon': 22.53})]
        result = retract_fake_numbers(offers)
        assert result['to_fix'] == 1
        assert result['inactive_to_fix'] == 1
        assert offers[0]['address']['full'] == 'Zana'
        assert offers[0]['address']['number'] is None
        assert offers[0]['address']['has_number'] is False
        assert offers[0]['address']['precision'] == 'street'

    def test_nie_rusza_prawdziwego_numeru(self):
        offers = [_offer('Lipowa 10', 'Lipowa', '10', REAL_NUMBER_TEXT)]
        result = retract_fake_numbers(offers)
        assert result['to_fix'] == 0
        assert result['kept'] == 1
        assert offers[0]['address']['full'] == 'Lipowa 10'

    def test_nie_przenosi_na_inna_ulice(self):
        """Nowy parse wskazuje inną ulicę → migracja wsadowa tego nie dotyka."""
        offers = [_offer('Zana 2', 'Zana', '2', 'Mieszkanie do wynajęcia przy ul. Lipowa, Lublin')]
        result = retract_fake_numbers(offers)
        assert result['to_fix'] == 0
        assert result['other_street'] == 1
        assert offers[0]['address']['full'] == 'Zana 2'

    def test_inny_adres_z_numerem_zostaje_bez_zmian(self):
        """Nowy parse ma numer, ale z innej ulicy → adres w bazie zostaje nietknięty."""
        offers = [_offer('Zana 2', 'Zana', '2', 'Mieszkanie przy ul. Lipowa 10')]
        result = retract_fake_numbers(offers)
        assert result['to_fix'] == 0
        assert offers[0]['address']['full'] == 'Zana 2'

    def test_bierze_coords_ulicy_z_cache(self):
        offers = [_offer('Zana 2', 'Zana', '2', FAKE_NUMBER_TEXT,
                         coords={'lat': 51.2400, 'lon': 22.5300})]
        cache = {'Zana': {'lat': 51.2450, 'lon': 22.5350}}
        retract_fake_numbers(offers, geocoding_cache=cache)
        assert offers[0]['address']['coords'] == {'lat': 51.2450, 'lon': 22.5350}

    def test_bez_cache_zostawia_dotychczasowe_coords(self):
        """Stary punkt to realny budynek przy tej samej ulicy — lepszy niż brak pinezki."""
        offers = [_offer('Zana 2', 'Zana', '2', FAKE_NUMBER_TEXT,
                         coords={'lat': 51.2400, 'lon': 22.5300})]
        retract_fake_numbers(offers, geocoding_cache={})
        assert offers[0]['address']['coords'] == {'lat': 51.2400, 'lon': 22.5300}
        assert offers[0]['address']['precision'] == 'street'

    def test_oferta_bez_numeru_jest_pomijana(self):
        offers = [_offer('Zana', 'Zana', None, FAKE_NUMBER_TEXT)]
        result = retract_fake_numbers(offers)
        assert result['considered'] == 0
        assert offers[0]['address']['full'] == 'Zana'

    def test_bezpiecznik_blokuje_masowa_zmiane(self):
        """Gdy parser padnie i chce przepisać całą bazę — migracja się nie wykonuje."""
        offers = [_offer(f'Zana {i}', 'Zana', str(i), FAKE_NUMBER_TEXT)
                  for i in range(MIN_OFFERS_FOR_RATIO_GUARD + 5)]
        result = retract_fake_numbers(offers)
        assert result['blocked'] is not None
        assert result['to_fix'] > len(offers) * MAX_RETRACTION_RATIO
        # nic nie zostało zmienione
        assert all(o['address']['number'] is not None for o in offers)


class TestScanIntegration:
    @pytest.fixture
    def agent(self, tmp_path):
        db = {'last_scan': None, 'next_scan': None, 'offers': []}
        data_file = tmp_path / 'offers.json'
        data_file.write_text(json.dumps(db), encoding='utf-8')
        return SonarMieszkaniowy(data_file=str(data_file),
                                 removed_file=str(tmp_path / 'removed.json'))

    def test_migracja_odpala_sie_raz(self, agent):
        agent.database['offers'] = [
            _offer('Zana 2', 'Zana', '2', FAKE_NUMBER_TEXT, coords={'lat': 51.24, 'lon': 22.53}),
            *[_offer(f'Lipowa {i}', 'Lipowa', '10', REAL_NUMBER_TEXT)
              for i in range(MIN_OFFERS_FOR_RATIO_GUARD)],
        ]
        agent._migrate_legacy_addresses()
        assert agent.database['address_parser_version'] == ADDRESS_PARSER_VERSION
        assert agent.database['offers'][0]['address']['full'] == 'Zana'

        # drugi przebieg nie może już nic ruszać
        agent.database['offers'][0]['address'] = {
            'full': 'Zana 5', 'street': 'Zana', 'number': '5', 'has_number': True}
        agent._migrate_legacy_addresses()
        assert agent.database['offers'][0]['address']['full'] == 'Zana 5'

    def test_zablokowana_migracja_nie_stempluje_wersji(self, agent):
        agent.scan_logger.start_scan()
        agent.database['offers'] = [
            _offer(f'Zana {i}', 'Zana', str(i), FAKE_NUMBER_TEXT)
            for i in range(MIN_OFFERS_FOR_RATIO_GUARD + 5)]
        agent._migrate_legacy_addresses()

        # brak stempla = migracja spróbuje ponownie po naprawie parsera
        assert 'address_parser_version' not in agent.database
        errors = agent.scan_logger.current_scan['errors']
        assert errors, "Zablokowana migracja ma trafić do błędów skanu (⚠️ w monitoringu)"
        assert 'parser' in errors[0]['message'].lower()


class TestDropRejectedLabels:
    """FIX 2026-08-10: etykieta, której parser już nie uznaje za adres, schodzi
    z mapy także ofertom siedzącym w bazie. `_update_existing_offer` umie adres
    tylko poprawić, a ofert nieaktywnych scraper w ogóle nie odwiedza.
    """

    JUNK_TEXT = 'Wynajmę mieszkanie, wolne miejsca parkingowe w garażu podziemnym'
    ADJECTIVE_TEXT = 'Do wynajęcia przytulna kawalerka, blisko uczelni, umeblowana'
    REAL_TEXT = 'Do wynajęcia mieszkanie przy ul. Lipowa 10 w Lublinie'

    def test_zdejmuje_smieciowa_etykiete(self):
        offers = [_offer('Wolne', 'Wolne', None, self.JUNK_TEXT,
                         coords={'lat': 51.24, 'lon': 22.53})]
        result = drop_rejected_labels(offers)

        assert result['to_fix'] == 1
        assert offers[0]['address']['full'] == ''
        assert offers[0]['address']['precision'] == 'none'

    def test_zdejmuje_przymiotnik_bedacy_nazwa_ulicy(self):
        """„Przytulna" to realna ulica Lublina — o odrzuceniu decyduje kontekst."""
        offers = [_offer('Przytulna', 'Przytulna', None, self.ADJECTIVE_TEXT)]
        assert drop_rejected_labels(offers)['to_fix'] == 1
        assert offers[0]['address']['full'] == ''

    def test_nie_rusza_adresu_ktory_parser_nadal_widzi(self):
        offers = [_offer('Lipowa 10', 'Lipowa', '10', self.REAL_TEXT, active=True)]
        assert drop_rejected_labels(offers)['to_fix'] == 0
        assert offers[0]['address']['full'] == 'Lipowa 10'

    def test_nie_rusza_realnej_ulicy_bez_kontekstu_przymiotnikowego(self):
        """Opis bez adresu, ale etykieta to realna ulica z innego źródła
        (np. z tytułu, którego stare oferty nie mają w bazie) — zostaje."""
        offers = [_offer('Narutowicza', 'Narutowicza', None,
                         'Mieszkanie dwupokojowe, umeblowane, od zaraz')]
        assert drop_rejected_labels(offers)['to_fix'] == 0
        assert offers[0]['address']['full'] == 'Narutowicza'

    def test_bezpiecznik_blokuje_masowe_czyszczenie(self):
        offers = [_offer(f'Wolne{i}', f'Wolne{i}', None, self.JUNK_TEXT)
                  for i in range(MIN_OFFERS_FOR_RATIO_GUARD + 5)]
        result = drop_rejected_labels(offers)

        assert result['blocked'] and 'awarię parsera' in result['blocked']
        assert all(o['address']['full'].startswith('Wolne') for o in offers)

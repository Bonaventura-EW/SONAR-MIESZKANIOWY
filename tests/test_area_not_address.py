"""Adresy opisujące OBSZAR nie dostają pinezki (FIX 2026-08-08).

Nazwy osiedli („Botanik", „Piastowskie"), instytucji („Uniwersytetu Medycznego")
i resztek po parserze („Wolne", „Miejsca") dostawały punkt gdzieś w tej okolicy
i na mapie wyglądały jak normalny adres. Trafiają teraz do warstwy „bez lokacji".
"""

import json

import pytest

from main import SonarMieszkaniowy


@pytest.fixture
def agent(tmp_path):
    db = {'last_scan': None, 'next_scan': None, 'offers': []}
    data_file = tmp_path / 'offers.json'
    data_file.write_text(json.dumps(db), encoding='utf-8')
    return SonarMieszkaniowy(data_file=str(data_file),
                             removed_file=str(tmp_path / 'removed.json'))


COORDS = {'lat': 51.2465, 'lon': 22.5684}


class TestRozpoznanieObszaru:
    @pytest.mark.parametrize("label", [
        'Wrotków', 'Rury', 'Prestige',            # dzielnice/osiedla z OSM
        'Botanik', 'Piastowskie', 'Skarpa', 'Poręba',   # osiedla spoza OSM
        'Uniwersytetu Medycznego',                # instytucja
        'Wolne', 'Miejsca', 'Piętro', 'Stokrotka',      # śmieci parsera
        'Nowe',                  # śmieć, który jest tylko PODCIĄGIEM „Nowe Sady"
    ])
    def test_obszar_i_smiec_bez_pinezki(self, label):
        assert SonarMieszkaniowy._is_area_not_address(label) is True

    @pytest.mark.parametrize("label", [
        'Lipowa', 'Krakowskie Przedmieście', 'Chodźki',
        'Racławickiej',          # odmiana Alej Racławickich — realna ulica
        'Aleja Racławickiej',    # ta sama ulica z prefiksem z ogłoszenia
        'Sekutowicza',           # skrót od „Bazylego Sekutowicza"
    ])
    def test_realna_ulica_zostaje_na_mapie(self, label):
        assert SonarMieszkaniowy._is_area_not_address(label) is False

    def test_pusta_etykieta_nie_wywraca(self):
        assert SonarMieszkaniowy._is_area_not_address('') is False

    def test_osiedle_nie_udaje_podobnej_ulicy(self):
        """Regresja 2026-08-08: l.mn.→l.poj. po stronie ZAPYTANIA robiło
        z osiedla „Piastowskie" ulicę „Piastowska" — inne, ale realne miejsce.
        Ta zamiana należy do indeksu (`index_variants`), nie do zapytania."""
        from street_whitelist import index_variants, name_variants
        assert 'piastowska' not in name_variants('Piastowskie')
        assert 'raclawicka' in index_variants('Aleje Racławickie'), \
            'Indeks musi znać formę pojedynczą — inaczej „Racławickiej" traci ulicę'


class TestPrzejscieBazy:
    def _offer(self, full, coords=COORDS, active=True):
        return {'id': f'x-{full}', 'active': active,
                'address': {'full': full, 'street': full, 'number': None,
                            'has_number': False, 'precision': 'street',
                            **({'coords': coords} if coords else {})}}

    def test_zdejmuje_pinezke_obszarowi(self, agent):
        agent.database['offers'] = [self._offer('Botanik')]
        agent._demote_non_street_pins()
        addr = agent.database['offers'][0]['address']
        assert 'coords' not in addr
        assert addr['precision'] == 'none'

    def test_nie_rusza_ulicy(self, agent):
        agent.database['offers'] = [self._offer('Lipowa')]
        agent._demote_non_street_pins()
        assert agent.database['offers'][0]['address']['coords'] == COORDS

    @pytest.mark.parametrize("label,expected", [
        ('Piłsudskiego Okna', 'Piłsudskiego'),
        ('Sekutowicza Mieszkanie', 'Sekutowicza'),   # realna ulica + śmieć w ogonie
        ('Granata NOWE', 'Granata'),
    ])
    def test_najpierw_probuje_sprzatnac_etykiete(self, agent, label, expected):
        """Etykieta z doklejonym śmieciem ma zostać ulicą z pinezką, nie trafić
        do bez-lokacji — sprzątamy napis, punkt zostaje na miejscu."""
        agent.database['offers'] = [self._offer(label)]
        agent._demote_non_street_pins()
        addr = agent.database['offers'][0]['address']
        assert addr['full'] == expected
        assert addr['coords'] == COORDS
        assert addr['precision'] == 'street'

    def test_jest_idempotentne(self, agent):
        agent.database['offers'] = [self._offer('Botanik')]
        agent._demote_non_street_pins()
        agent._demote_non_street_pins()
        assert agent.database['offers'][0]['address']['precision'] == 'none'

    def test_dotyka_takze_ofert_nieaktywnych(self, agent):
        agent.database['offers'] = [self._offer('Wolne', active=False)]
        agent._demote_non_street_pins()
        assert 'coords' not in agent.database['offers'][0]['address']

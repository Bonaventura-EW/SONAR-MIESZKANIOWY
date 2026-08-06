"""Adres brany NAJPIERW z tytułu, dopiero potem z treści (FIX 2026-08-06).

Tytuł jest krótki i pisany świadomie („Cyrkoniowa 7 - kawalerka do wynajęcia"),
więc adres w nim jest pewniejszy niż sklejka tytuł+opis, z której parser potrafi
zbudować pseudo-adres. Pomiar na 703 aktywnych ofertach: 22 adresy lepsze,
2 gorsze, reszta bez zmian.
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


def _raw(title, description=''):
    return {'title': title, 'description': description,
            'url': 'https://www.olx.pl/d/oferta/x-CID3-IDx.html'}


class TestAdresZTytulu:
    def test_tytul_z_numerem_wygrywa(self, agent):
        raw = _raw('Cyrkoniowa 7 - kawalerka do wynajęcia (KUL)',
                   'Mieszkanie 2 pokojowe, blisko ul. Lipowa, świetna lokalizacja')
        result = agent._address_from_title(raw, raw['title'] + ' ' + raw['description'])
        assert result is not None
        assert result['full'] == 'Cyrkoniowa 7'

    def test_tytul_z_prefiksem_bez_numeru_jest_ok(self, agent):
        raw = _raw('Mieszkanie 2-pokojowe, ul. Kustronia', 'Przytulne mieszkanie')
        result = agent._address_from_title(raw, raw['title'] + ' ' + raw['description'])
        assert result is not None
        assert result['full'] == 'Kustronia'
        assert result['has_number'] is False

    def test_numer_dobrany_z_tresci_dla_tej_samej_ulicy(self, agent):
        """„ul. Głęboka" w tytule + „Głębokiej 21" w opisie → Głęboka 21."""
        raw = _raw('Wynajmę mieszkanie 46 m2 - ul. Głęboka w Lublinie',
                   'Wynajmę mieszkanie przy ul. Głębokiej 21, drugie piętro')
        result = agent._address_from_title(raw, raw['title'] + ' ' + raw['description'])
        assert result is not None
        assert result['has_number'] is True
        assert result['number'] == '21'

    def test_numer_z_innej_ulicy_nie_jest_doklejany(self, agent):
        raw = _raw('Mieszkanie ul. Kustronia',
                   'Mieszkanie przy ul. Lipowa 10 w centrum Lublina')
        result = agent._address_from_title(raw, raw['title'] + ' ' + raw['description'])
        assert result is not None
        assert result['full'] == 'Kustronia'
        assert result['has_number'] is False

    def test_smieciowy_tytul_oddaje_pole_tresci(self, agent):
        """Tytuł bez realnej ulicy → None, caller idzie do treści."""
        raw = _raw('Nowoczesne mieszkanie 2 pokoje z klimatyzacją',
                   'Mieszkanie przy ul. Lipowa 10')
        assert agent._address_from_title(raw, raw['title'] + ' ' + raw['description']) is None

    def test_nazwa_bez_prefiksu_i_bez_numeru_odrzucona(self, agent):
        """Sama nazwa w tytule, bez „ul." i bez numeru, jest za słabą przesłanką."""
        raw = _raw('Mieszkanie Wieniawa Lipowa okolice', 'Coś tam')
        result = agent._address_from_title(raw, raw['title'])
        assert result is None or result.get('has_number') is True

    def test_brak_tytulu_nie_wywraca_parsowania(self, agent):
        assert agent._address_from_title({'description': 'x'}, 'x') is None
        assert agent._address_from_title(_raw(''), '') is None


class TestSameStreet:
    def test_odmiana_to_ta_sama_ulica(self):
        assert SonarMieszkaniowy._same_street({'street': 'Głęboka'}, {'street': 'Głębokiej'})
        assert SonarMieszkaniowy._same_street({'street': 'Nałęczowskiej'}, {'street': 'Nałęczowska'})

    def test_skrot_nazwiska_to_ta_sama_ulica(self):
        assert SonarMieszkaniowy._same_street({'street': 'Chodźki'},
                                              {'street': 'Doktora Witolda Chodźki'})

    def test_inne_ulice_to_nie_to_samo(self):
        assert not SonarMieszkaniowy._same_street({'street': 'Lipowa'}, {'street': 'Kustronia'})
        assert not SonarMieszkaniowy._same_street({'street': ''}, {'street': 'Lipowa'})


class TestTrimLeadingJunk:
    """Reklamowy przedrostek w tytule („BEZPOŚREDNIO Nałęczowska 20")."""

    def test_obcina_przedrostek_gdy_ogon_jest_ulica(self):
        result = SonarMieszkaniowy._trim_leading_junk({
            'street': 'BEZPOŚREDNIO Nałęczowska', 'number': '20',
            'full': 'BEZPOŚREDNIO Nałęczowska 20', 'has_number': True})
        assert result['full'] == 'Nałęczowska 20'
        assert result['street'] == 'Nałęczowska'

    def test_nie_rusza_prawdziwej_dwuczlonowej_nazwy(self):
        for street, full in [('Krakowskie Przedmieście', 'Krakowskie Przedmieście 51'),
                             ('Jana Sawy', 'Jana Sawy 3')]:
            result = SonarMieszkaniowy._trim_leading_junk({
                'street': street, 'number': full.split()[-1], 'full': full, 'has_number': True})
            assert result['full'] == full, f"Skrócono poprawną nazwę: {full}"

    def test_nie_rusza_nazwy_z_prefiksem(self):
        """'Aleja Racławickie 5' — parser już rozdzielił prefiks, `full` != `street`."""
        result = SonarMieszkaniowy._trim_leading_junk({
            'street': 'Racławickie', 'number': '5', 'full': 'Aleja Racławickie 5', 'has_number': True})
        assert result['full'] == 'Aleja Racławickie 5'

    def test_bez_numeru_zostaje_sama_ulica(self):
        result = SonarMieszkaniowy._trim_leading_junk({
            'street': 'POLECAM Lipowa', 'number': None,
            'full': 'POLECAM Lipowa', 'has_number': False})
        assert result['full'] == 'Lipowa'

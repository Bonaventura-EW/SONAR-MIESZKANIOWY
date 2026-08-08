"""Fallback nazwiskowy nie może obchodzić filtrów ścieżki głównej (FIX 2026-08-08).

`POLISH_SURNAME_PATTERN` łapie „NAZWA w dopełniaczu + numer" i przez lata zwracał
wynik z pominięciem WSZYSTKICH filtrów, które ścieżka główna dopiero co zastosowała.
Efekt: 21 aktywnych ofert stało na „ulicy", której w Lublinie nie ma — a że fallback
zwraca `has_number=True`, mapa uznawała je za adres DOKŁADNY.

Trzy filtry, których brakowało: fałszywe adresy („X minut/metrów", metraż), lista
instytucji, i przynależność nazwy do whitelisty ulic.
"""

import pytest

from address_parser import AddressParser


@pytest.fixture(scope='module')
def parser():
    return AddressParser()


def _full(parser, text):
    result = parser.extract_address(text)
    return result and result.get('full')


class TestMetrazNieJestAdresem:
    def test_powierzchnia_nie_jest_ulica(self, parser):
        """Realny przypadek: ulica stoi w tekście, a parser brał metraż."""
        text = ('Wynajmę kawalerkę w centrum Lublina ul. Wschodnia, IV piętro. '
                'Powierzchnia 32 m kw. – pokój, kuchnia, łazienka.')
        assert _full(parser, text) == 'Wschodnia'

    def test_minuty_dojscia_nie_sa_numerem(self, parser):
        """„Nałęczowska 2 minuty pieszą" to czas marszu, nie numer domu."""
        text = ('Mieszkanie przy Alei Kraśnickiej. Najbliższy przystanek to '
                'Nałęczowska 2 minuty pieszą.')
        assert _full(parser, text) != 'Nałęczowska 2'


class TestNazwaMusiBycUlica:
    @pytest.mark.parametrize("text,junk", [
        ('Mieszkanie na Kalinie, na ul. Niepodległości, w zielonej okolicy. '
         'Kalina 38 to dobry adres.', 'Kalina 38'),
        ('Do wynajęcia mieszkanie na Wrotkowie. W cenie Netia 30 Mb internetu.', 'Netia 30'),
        ('Umeblowane mieszkanie przy ul. Głębokiej. Sypialnia 1 osobowa.', 'Sypialnia 1'),
    ])
    def test_smiec_nie_udaje_adresu(self, parser, text, junk):
        assert _full(parser, text) != junk

    @pytest.mark.parametrize("text,expected", [
        ('Do wynajęcia mieszkanie Langiewicza 3A, po remoncie.', 'Langiewicza 3A'),
        ('Mieszkanie Słowackiego 12, blisko centrum.', 'Słowackiego 12'),
    ])
    def test_realne_nazwisko_z_numerem_dziala_dalej(self, parser, text, expected):
        """Fallback ma nadal robić to, po co powstał."""
        assert _full(parser, text) == expected


class TestBrakWhitelistyNieOdrzuca:
    def test_bez_modulu_whitelist_fallback_przepuszcza(self, monkeypatch):
        """Whitelist tylko *wpuszcza* — jej brak nie może zacząć odrzucać adresów."""
        import builtins
        real_import = builtins.__import__

        def blocked(name, *args, **kwargs):
            if name == 'street_whitelist':
                raise ImportError('brak modułu')
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, '__import__', blocked)
        assert AddressParser._is_whitelisted_street('CokolwiekNieznanego') is True

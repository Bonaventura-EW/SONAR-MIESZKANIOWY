"""
Address Parser - ekstrakcja adresów z opisów ogłoszeń
Akceptuje formaty:
- "Narutowicza 5" (bez "ul.")
- "Rynek 8" (bez określenia typu)
- "al. Andersa 13 lok. 5"
- "ul. Racławickie 12/2"
- "Aleja Kraśnicka 73a" - zachowuje prefiks Aleja!
"""

import re
from typing import Optional, Dict

class AddressParser:
    # Prefiksy ulic - teraz jako GRUPY do wyciągnięcia
    # Grupa 1: prefiks (opcjonalny)
    # Grupa 2: nazwa ulicy
    # Grupa 3: numer
    # UWAGA: Dłuższe prefiksy MUSZĄ być przed krótszymi
    PREFIX_PATTERN = r'(ulica|ul\.|ul|aleja|aleje|al\.|al|plac|pl\.|pl|osiedle|os\.|os)?\s*'
    
    # Główny pattern adresu - z prefixem jako opcjonalną grupą
    # UWAGA: Dłuższe prefiksy MUSZĄ być przed krótszymi (ulica przed ul, aleja przed al, itd.)
    ADDRESS_PATTERN = re.compile(
        rf'(ulica|ul\.|ul|aleja|aleje|al\.|al|plac|pl\.|pl|osiedle|os\.|os)?\s*([A-ZŚĆŁĄĘÓŻŹŃ][a-zśćłąęóżźń]+(?:\s+[A-ZŚĆŁĄĘÓŻŹŃ]?[a-zśćłąęóżźń]+)?)\s+(\d+[a-zA-Z]?(?:/\d+)?(?:\s+lok\.\s+\d+)?)',
        re.UNICODE | re.IGNORECASE
    )
    
    # NOWY: Wzorzec dla polskich nazwisk w dopełniaczu (Langiewicza, Słowackiego, Czuby itd.)
    # Łapie: "[Nazwisko kończące się na -a/-cza/-sza/-ego/-iego/-owej/-skiej] + numer"
    POLISH_SURNAME_PATTERN = re.compile(
        r'\b([A-ZŚĆŁĄĘÓŻŹŃ][a-zśćłąęóżźń]*(?:cza|sza|ego|iego|owej|skiej|skiego|ckiego|nej|nego|wej|wego|ej|a))\s+(\d+[a-zA-Z]?(?:/\d+)?)\b',
        re.UNICODE
    )
    
    # Mapowanie prefiksów do pełnych nazw (dla geokodowania)
    PREFIX_MAP = {
        'ul.': '',  # ul. usuwamy
        'ulica': '',
        'al.': 'Aleja',  # al. zamieniamy na Aleja
        'aleja': 'Aleja',
        'aleje': 'Aleje',
        'pl.': 'Plac',
        'plac': 'Plac',
        'os.': 'Osiedle',
        'osiedle': 'Osiedle'
    }
    
    def __init__(self):
        pass
    
    def extract_address(self, text: str) -> Optional[Dict[str, str]]:
        """
        Wyciąga adres z tekstu.
        
        Args:
            text: Tekst do przeszukania (tytuł + opis)
            
        Returns:
            Dict z kluczami: street, number, full lub None jeśli nie znaleziono
        """
        if not text:
            return None
        
        # FILTR 1: Sprawdź czy tekst zawiera "X metrów od" - to NIE jest adres
        if re.search(r'\d+\s*metr[oó]w\s+(od|do)', text, re.IGNORECASE):
            return None
        
        # FILTR 2: Wykryj fałszywe adresy typu "NAZWA 10 minut" / "NAZWA 5 min"
        # Przykład: "UMCS 10 minut pieszo" - to NIE jest adres "UMCS 10"
        false_address_pattern = re.compile(
            r'\b([A-ZŚĆŁĄĘÓŻŹŃ][A-Za-zśćłąęóżźń]*)\s+(\d+)\s*(minut|min\.?|minuty?|sekund|sek\.?|godzin|godz\.?|metr[oó]w|km|m\b)',
            re.IGNORECASE | re.UNICODE
        )
        # Zapamiętaj fałszywe "adresy" do późniejszego odrzucenia
        false_addresses = set()
        for match in false_address_pattern.finditer(text):
            false_addr = f"{match.group(1)} {match.group(2)}"
            false_addresses.add(false_addr.lower())
        
        # Słowa które NIGDY nie mogą być nazwą ulicy (instytucje, uczelnie, itp.)
        # Te słowa + numer to prawie zawsze "X minut od", "X metrów od"
        non_street_names = {
            'umcs', 'kul', 'politechnika', 'up', 'uniwersytet', 'szkoła', 'szpital',
            'galeria', 'centrum', 'rondo', 'przystanek', 'dworzec', 'stacja',
            'sklep', 'biedronka', 'lidl', 'żabka', 'rossmann', 'leclerc', 'auchan', 'kaufland',
            'park', 'las', 'jezioro', 'rzeka', 'plaża', 'stadion', 'hala', 'basen',
            'lsm', 'czuby', 'kalinowszczyzna', 'tatary', 'bronowice', 'wieniawa',
            # Dodatkowe
            'carrefour', 'tesco', 'empik', 'media', 'saturn', 'decathlon',
            'poczta', 'urząd', 'sąd', 'kościół', 'cerkiew', 'meczet', 'synagoga',
            'apteka', 'bank', 'hotel', 'restauracja', 'kawiarnia', 'pub', 'klub',
            'kino', 'teatr', 'muzeum', 'biblioteka', 'szpital', 'klinika', 'przychodnia'
        }
        
        # SPECJALNY PRZYPADEK: znane ulice w Lublinie które mogą zaczynać się małą literą lub nie pasować do wzorca
        # WYMAGA NUMERU! (usunięto fallback bez numeru)
        lowercase_streets = ['zimowa', 'wiosenna', 'letnia', 'jesienna']
        special_streets = ['botaniczna', 'morsztynów'] + lowercase_streets
        
        for street_name in special_streets:
            # Pattern z numerem (WYMAGANY!)
            pattern_num = rf'\b{street_name}\s+(\d+[a-zA-Z]?(?:/\d+)?)'
            match = re.search(pattern_num, text, re.IGNORECASE)
            if match:
                number = match.group(1)
                # Walidacja numeru
                try:
                    num_str = number.rstrip('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ/')
                    num_value = int(num_str)
                    if num_value <= 250:
                        return {
                            'street': street_name.capitalize(),
                            'number': number,
                            'full': f"{street_name.capitalize()} {number}"
                        }
                except ValueError:
                    pass
        
        # Słowa które NIE mogą być nazwą ulicy
        excluded_words_lower = {
            'pokój', 'przy', 'obok', 'blisko', 'centrum', 'okolice', 'minut', 'minutę', 'rok', 'lata',
            'jednoosobowy', 'dwuosobowy', 'trzoosobowy', 'osobowy',
            'dla', 'bez', 'lub', 'osób', 'osoby',
            # NOWE: nazwy dzielnic Lublina (nie są ulicami)
            'wieniawa', 'śródmieście', 'bronowice', 'czuby', 'kalinowszczyzna', 'tatary',
            'czechów', 'sławinek', 'sławin', 'abramowice', 'konstantynów', 'ponikwoda',
            'głusk', 'węglin', 'felin', 'hajdów',
            # NOWE: słowa z ogłoszeń które nie są ulicami
            'net', 'ciepło', 'internet', 'wifi', 'balkon', 'ogród', 'parking',
            'od', 'do', 'za', 'na', 'po', 'we', 'ze',
            # NOWE: słowa które parser myli z ulicami
            'stancja', 'mieszkaniu', 'mieszkanie', 'przechowywania', 'powierzchni',
            'fajna', 'fajny', 'studentki', 'studenta', 'lokalu', 'budynku', 'budynek',
            'pokoju', 'kuchni', 'salonu', 'łazienki', 'sypialni',
            # KRYTYCZNE: pseudo-adresy (blok, wieżowiec, kamienica)
            'blok', 'bloku', 'bloków', 'wieżowiec', 'wieżowca', 'kamienica', 'kamienicy',
            # KRYTYCZNE: pseudo-ulice wyciągnięte z opisów (rachunki, pokoje, itp.)
            'rachunki', 'pokoje', 'około', 'dostępny', 'dostępna', 'dostępne',
            'wynajmę', 'wynajem', 'located', 'gyms', 'available', 'meters',
            'numer', 'kontaktowy', 'telefon', 'kontakt', 'number',
            # KRYTYCZNE: Instytucje, sklepy, uczelnie - NIE są ulicami!
            'umcs', 'kul', 'politechnika', 'up', 'uniwersytet', 'szkoła', 'szpital',
            'galeria', 'rondo', 'przystanek', 'dworzec', 'stacja',
            'sklep', 'biedronka', 'lidl', 'żabka', 'rossmann', 'leclerc', 'auchan', 'kaufland',
            'park', 'las', 'jezioro', 'rzeka', 'plaża', 'stadion', 'hala', 'basen', 'lsm',
            'carrefour', 'tesco', 'empik', 'media', 'saturn', 'decathlon',
            'poczta', 'urząd', 'sąd', 'kościół', 'cerkiew', 'meczet', 'synagoga',
            'apteka', 'bank', 'hotel', 'restauracja', 'kawiarnia', 'pub', 'klub',
            'kino', 'teatr', 'muzeum', 'biblioteka', 'klinika', 'przychodnia'
        }
        
        # Szukamy WSZYSTKICH dopasowań (prefiks + ulica + numer)
        matches = self.ADDRESS_PATTERN.finditer(text)
        
        for match in matches:
            prefix = match.group(1)  # może być None
            street = match.group(2).strip()
            number = match.group(3).strip()
            
            # Sprawdź minimum 4 litery w nazwie ulicy (żeby wykluczyć "dla", "bez" etc)
            if len(street.replace(' ', '')) < 4:
                continue
            
            # NOWY FILTR: Sprawdź czy to nie jest fałszywy adres (np. "UMCS 10" z "UMCS 10 minut")
            potential_addr = f"{street} {number.split('/')[0].split()[0]}"
            if potential_addr.lower() in false_addresses:
                print(f"      ⚠️ Odrzucono fałszywy adres: {potential_addr} (wykryto 'X minut/metrów')")
                continue
            
            # NOWY FILTR: Sprawdź czy nazwa ulicy to nie instytucja/miejsce (nie ulica)
            if street.lower() in non_street_names:
                print(f"      ⚠️ Odrzucono: '{street}' to nie jest nazwa ulicy")
                continue
            
            # Sprawdź czy którekolwiek słowo w nazwie ulicy NIE jest słowem wykluczonym
            street_words = street.split()
            is_valid = True
            
            for word in street_words:
                if word.lower() in excluded_words_lower:
                    is_valid = False
                    break
            
            if not is_valid:
                continue
            
            # Wyciągnij główny numer (przed / lub lok.)
            main_number = number.split('/')[0].split()[0]
            
            # FILTR BEZPIECZEŃSTWA: Odrzuć numery z literą O/o zaraz po cyfrze (błąd OCR)
            # Przykład: "1O", "10O", "2o" - prawdopodobnie błąd, powinno być "10", "100", "20"
            if re.search(r'\d[Oo](?:[^a-zA-Z]|$)', main_number):
                print(f"      ⚠️ Odrzucono podejrzany numer: {number} (prawdopodobnie błąd OCR: 'O' zamiast '0')")
                continue
            
            # FILTR 2: Sprawdź czy numer jest rozsądny (max 250)
            # Numery >250 to prawdopodobnie CENY np. "Samsonowicza 500 zł"
            try:
                # Usuń literę na końcu jeśli jest (np. "12a" -> "12")
                num_str = main_number.rstrip('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ')
                num_value = int(num_str)
                if num_value > 250:
                    continue  # Ignoruj, to prawdopodobnie cena
            except ValueError:
                pass  # Jeśli nie można sparsować, to OK
            
            # Normalizacja: usuwamy wielokrotne spacje
            street = ' '.join(street.split())
            number = ' '.join(number.split())
            
            # NOWE: Buduj pełny adres z prefixem (jeśli jest)
            full_address = street
            if prefix:
                prefix_lower = prefix.lower().rstrip('.')
                # Mapuj prefiks na pełną nazwę
                if prefix_lower in ['al', 'aleja']:
                    full_address = f"Aleja {street}"
                elif prefix_lower in ['aleje']:
                    full_address = f"Aleje {street}"
                elif prefix_lower in ['pl', 'plac']:
                    full_address = f"Plac {street}"
                elif prefix_lower in ['os', 'osiedle']:
                    full_address = f"Osiedle {street}"
                # ul./ulica - pomijamy, zostawiamy samą nazwę ulicy
            
            return {
                'street': street,
                'number': number,
                'full': f"{full_address} {number}"
            }
        
        # NOWY FALLBACK: Wzorzec dla polskich nazwisk w dopełniaczu
        # Łapie przypadki jak "Langiewicza 3A", "Słowackiego 12" bez prefiksu
        surname_matches = self.POLISH_SURNAME_PATTERN.finditer(text)
        
        for match in surname_matches:
            street = match.group(1).strip()
            number = match.group(2).strip()
            
            # Sprawdź minimum 5 liter (żeby wykluczyć "Pokoja 5" itp.)
            if len(street) < 5:
                continue
            
            # Sprawdź czy nie jest wykluczonym słowem
            if street.lower() in excluded_words_lower:
                continue
            
            # Walidacja numeru (max 250)
            try:
                main_num = number.rstrip('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ/').split('/')[0]
                if int(main_num) > 250:
                    continue
            except ValueError:
                continue
            
            return {
                'street': street,
                'number': number,
                'full': f"{street} {number}"
            }
        
        # BRAK FALLBACK - Wymagamy NUMERU domu!
        # Adresy bez numeru (np. "ul. Niecała") są zbyt nieprecyzyjne dla mapy
        return None
    
    def validate_lublin_address(self, address: str) -> bool:
        """
        Sprawdza czy adres wygląda na prawdziwy adres w Lublinie.
        Filtruje oczywiste błędy typu "123 abc" itp.
        
        Args:
            address: Pełny adres do walidacji
            
        Returns:
            True jeśli adres wygląda poprawnie
        """
        if not address:
            return False
        
        # Musi zawierać przynajmniej jedną literę i jedną cyfrę
        has_letter = any(c.isalpha() for c in address)
        has_digit = any(c.isdigit() for c in address)
        
        if not (has_letter and has_digit):
            return False
        
        # Nie może być zbyt krótki (min. "A 1")
        if len(address) < 3:
            return False
        
        return True


# Testy jednostkowe
if __name__ == "__main__":
    parser = AddressParser()
    
    test_cases = [
        ("Narutowicza 5", "Narutowicza 5"),  # Bez 'przy' - powinno działać
        ("ul. Rynek 8, centrum", "Rynek 8"),
        ("al. Andersa 13 lok. 5", "Aleja Andersa 13 lok. 5"),  # Prefiks zachowany
        ("Aleje Racławickie 12/2", "Aleje Racławickie 12/2"),
        ("Os. Przyjaźni 23", "Osiedle Przyjaźni 23"),  # Prefiks zachowany
        ("Langiewicza 3A", "Langiewicza 3A"),  # Z literą
        ("zimowa 10", "Zimowa 10"),  # Kapitalizacja
        ("Czechów okolice", None),  # brak numeru
        ("Przy rondzie Chatki Żaka", None),  # brak numeru
        ("5 minut od centrum", None),  # nie adres
        ("100 metrów od UMCS", None),  # metrów od
        # NOWE: Fałszywe adresy typu "X minut od"
        ("UMCS 10 minut pieszo", None),  # UMCS to nie ulica!
        ("Biedronka 5 min stąd", None),  # Biedronka to nie ulica!
        ("KUL 15 minut autobusem", None),  # KUL to nie ulica!
        ("Politechnika 3 min pieszo", None),  # Politechnika to nie ulica!
        ("LSM 10 minut od centrum", None),  # LSM to dzielnica, nie ulica!
        ("Galeria 5 minut stąd", None),  # Galeria to nie ulica!
        # Prawdziwe adresy powinny nadal działać
        ("ul. Lipowa 10, blisko UMCS", "Lipowa 10"),  # Prawdziwy adres
    ]
    
    print("🧪 Testy Address Parser:\n")
    for text, expected in test_cases:
        result = parser.extract_address(text)
        extracted = result['full'] if result else None
        status = "✅" if extracted == expected else "❌"
        print(f"{status} '{text}' → {extracted}")
        if extracted != expected:
            print(f"   Oczekiwano: {expected}")

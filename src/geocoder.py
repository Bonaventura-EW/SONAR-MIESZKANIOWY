"""
Geocoder - zamiana adresów na współrzędne GPS
Używa Nominatim API (OpenStreetMap) + cache w JSON
+ walidacja czy adres jest w Lublinie (bounding box)
"""

import json
import re
import time
from pathlib import Path
from typing import Optional, Dict
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut, GeocoderServiceError

# Bounding box Lublina (~20x25 km z marginesem)
# Pokrywa centrum + wszystkie dzielnice + przedmieścia
LUBLIN_BBOX = {
    'min_lat': 51.18,   # Południowa granica (~3km od skraju)
    'max_lat': 51.30,   # Północna granica (~3km zapasu)
    'min_lon': 22.42,   # Zachodnia granica
    'max_lon': 22.68    # Wschodnia granica
}

class Geocoder:
    def __init__(self, cache_file: str = "data/geocoding_cache.json"):
        self.cache_file = Path(cache_file)
        self.cache = self._load_cache()
        self.geolocator = Nominatim(user_agent="sonar-mieszkaniowy-lublin/1.0")
        self._geocoding_limited = False  # Gdy True: pomija fallbacki, używa tylko cache
        
    def _load_cache(self) -> Dict:
        """Ładuje cache z pliku JSON."""
        if self.cache_file.exists():
            try:
                with open(self.cache_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except json.JSONDecodeError:
                return {}
        return {}
    
    def _save_cache(self):
        """Zapisuje cache do pliku JSON."""
        self.cache_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.cache_file, 'w', encoding='utf-8') as f:
            json.dump(self.cache, f, ensure_ascii=False, indent=2)
    
    def is_in_lublin(self, coords: Dict[str, float]) -> bool:
        """
        Sprawdza czy współrzędne są w granicach Lublina (bounding box).
        
        Args:
            coords: Dict z kluczami 'lat' i 'lon'
            
        Returns:
            True jeśli w Lublinie, False jeśli poza
        """
        if not coords:
            return False
        
        return (
            LUBLIN_BBOX['min_lat'] <= coords['lat'] <= LUBLIN_BBOX['max_lat'] and
            LUBLIN_BBOX['min_lon'] <= coords['lon'] <= LUBLIN_BBOX['max_lon']
        )
    
    def geocode_address(self, address: str, max_retries: int = 3) -> Optional[Dict[str, float]]:
        """
        Geokoduje adres na współrzędne GPS.

        Args:
            address: Adres do geokodowania (np. "Narutowicza 5")
            max_retries: Maksymalna liczba prób

        Returns:
            Dict z lat, lon lub None jeśli nie znaleziono
        """
        if not address:
            return None

        # Zabezpieczenie: jeśli address jest dict (błąd wywołującego), wyciągnij string
        if isinstance(address, dict):
            address = address.get('full', '')
            if not address:
                return None

        # Sprawdzamy cache (pomijamy None-wpisy dla krótkich adresów — mogą mieć lepszy fallback)
        if address in self.cache and self.cache[address] is not None:
            return self.cache[address]

        # Gdy osiągnięto limit geocodowań w tym skanie — nie rób nowych requestów
        if self._geocoding_limited:
            return None

        # Pierwsza próba: oryginalny adres
        result = self._geocode_single(address, max_retries)
        if result is not None:
            return result

        # FALLBACK: Aleja ↔ Aleje (skrót "al." jest niejednoznaczny)
        # np. "Aleja Racławickie 28a" nie znajdzie, ale "Aleje Racławickie 28a" tak.
        alt_address = None
        if address.startswith('Aleja '):
            alt_address = 'Aleje ' + address[len('Aleja '):]
        elif address.startswith('Aleje '):
            alt_address = 'Aleja ' + address[len('Aleje '):]

        if alt_address and alt_address not in self.cache:
            print(f"   🔄 Fallback geocoder: {address!r} → {alt_address!r}")
            result = self._geocode_single(alt_address, max_retries)
            if result is not None:
                # Zapisz pod oryginalnym adresem - ten się uda następnym razem od razu
                self.cache[address] = result
                self._save_cache()
                return result

        # FALLBACK 2: usuń "lok. N" (nr lokalu) - Nominatim często go nie rozumie
        if ' lok. ' in address:
            simplified = re.sub(r'\s+lok\.\s+\d+', '', address)
            if simplified != address:
                print(f"   🔄 Fallback bez nr lokalu: {address!r} → {simplified!r}")
                result = self._geocode_single(simplified, max_retries)
                if result is not None:
                    self.cache[address] = result
                    self._save_cache()
                    return result
                # Spróbuj jeszcze z zamianą Aleja↔Aleje na uproszczonym
                alt2 = None
                if simplified.startswith('Aleja '):
                    alt2 = 'Aleje ' + simplified[len('Aleja '):]
                elif simplified.startswith('Aleje '):
                    alt2 = 'Aleja ' + simplified[len('Aleje '):]
                if alt2:
                    print(f"   🔄 Fallback uproszczony+Aleja/Aleje: → {alt2!r}")
                    result = self._geocode_single(alt2, max_retries)
                    if result is not None:
                        self.cache[address] = result
                        self._save_cache()
                        return result

        # FALLBACK 3: ulice bez numeru — dodaj prefix "ul." który pomaga Nominatim
        # np. "Organowej" → "ul. Organowej, Lublin"
        words = address.split()
        has_number = any(re.search(r'\d', w) for w in words)
        if not has_number and not address.startswith('ul.') and len(words) <= 3:
            ul_address = 'ul. ' + address
            if ul_address not in self.cache or self.cache.get(ul_address) is None:
                print(f"   🔄 Fallback ul. prefix: {address!r} → {ul_address!r}")
                result = self._geocode_single(ul_address, max_retries)
                if result is not None:
                    self.cache[address] = result
                    self._save_cache()
                    return result

        # FALLBACK 4: numer niestandardowy (2k, 18w, 20m) — usuń literę za numerem
        # np. "Koralowa 20" → spróbuj bez skrótu, "Nałęczowskiej 18w" → "Nałęczowskiej 18"
        cleaned = re.sub(r'(\d+)[a-zA-Z]+$', r'\1', address)
        if cleaned != address and cleaned not in self.cache:
            print(f"   🔄 Fallback bez sufiksu numeru: {address!r} → {cleaned!r}")
            result = self._geocode_single(cleaned, max_retries)
            if result is not None:
                self.cache[address] = result
                self._save_cache()
                return result

        # FALLBACK 5: konwersja dopełniacza → mianownik dla polskich ulic
        # Nominatim OSM często ma nazwy ulic w mianowniku (Organowa), 
        # a parser wyciąga dopełniacz (Organowej, Furmańskiej, Koralowej)
        nominative = self._genitive_to_nominative(address)
        if nominative and nominative != address and nominative not in self.cache:
            print(f"   🔄 Fallback mianownik: {address!r} → {nominative!r}")
            result = self._geocode_single(nominative, max_retries)
            if result is not None:
                self.cache[address] = result
                self._save_cache()
                return result

        return None

    def _genitive_to_nominative(self, address: str) -> str:
        """
        Próbuje skonwertować polską nazwę ulicy z dopełniacza na mianownik.
        Nominatim OSM ma nazwy ulic w mianowniku (Organowa nie Organowej).
        Obsługuje najczęstsze końcówki przymiotnikowe żeńskie i rzeczownikowe.
        """
        parts = address.rsplit(' ', 1)
        street = parts[0]
        num = parts[1] if len(parts) > 1 else ''

        conversions = [
            # Żeńskie przymiotnikowe: -owej → -owa, -skiej → -ska, -nej → -na itd.
            (r'owej$', 'owa'),
            (r'skiej$', 'ska'),
            (r'nej$', 'na'),
            (r'wej$', 'wa'),
            (r'iej$', 'ia'),
            (r'zej$', 'za'),
            # Dopełniacz -ej → -a (ogólna żeńska)
            (r'([b-df-hj-np-tv-z])ej$', r'\1a'),
            # Rzeczowniki: -iej → -ia, -skiej → -ska
            (r'ciej$', 'cia'),
            (r'dziej$', 'dzia'),
        ]
        for pattern, replacement in conversions:
            new_street = re.sub(pattern, replacement, street, flags=re.IGNORECASE)
            if new_street != street:
                return (f"{new_street} {num}").strip() if num else new_street

        return address

    def _geocode_single(self, address: str, max_retries: int = 3) -> Optional[Dict[str, float]]:
        """Pojedyncza próba geokodowania konkretnego adresu (bez fallbacku)."""
        # Zwróć z cache TYLKO gdy wynik jest nie-None
        if address in self.cache and self.cache[address] is not None:
            return self.cache[address]

        # Pełny adres z miastem
        full_address = f"{address}, Lublin, Poland"

        # Próbujemy geokodować
        for attempt in range(max_retries):
            try:
                location = self.geolocator.geocode(
                    full_address,
                    timeout=10,
                    language='pl'
                )

                if location:
                    coords = {
                        'lat': location.latitude,
                        'lon': location.longitude
                    }

                    # WALIDACJA: Sprawdź czy adres jest w Lublinie
                    if not self.is_in_lublin(coords):
                        print(f"⚠️ Odrzucono {address} - poza Lublinem (lat={coords['lat']:.4f}, lon={coords['lon']:.4f})")
                        # NIE cachujemy negatywnie - może fallback Aleja/Aleje pomoże
                        return None

                    # Zapisujemy do cache
                    self.cache[address] = coords
                    self._save_cache()
                    
                    return coords
                else:
                    # Nie znaleziono - zapisujemy jako None TYLKO gdy nie ma sensu retryować
                    # Nie cachuj None dla: Aleja/Aleje (fallback 1), adresów z dopełniaczem (fallback 5)
                    no_cache_patterns = (
                        address.startswith('Aleja ') or address.startswith('Aleje ') or
                        re.search(r'(owej|skiej|nej|wej|iej|zej)\s*(\d|$)', address, re.IGNORECASE)
                    )
                    if not no_cache_patterns:
                        self.cache[address] = None
                        self._save_cache()
                    return None
                    
            except GeocoderTimedOut:
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)  # Exponential backoff
                    continue
                else:
                    return None
                    
            except GeocoderServiceError as e:
                # 429 Rate limited — czekaj dłużej i retry
                if '429' in str(e):
                    wait = 5 * (attempt + 1)
                    print(f"   ⏳ Rate limit (429), czekam {wait}s...")
                    time.sleep(wait)
                    if attempt < max_retries - 1:
                        continue
                return None
        
        return None
    
    def batch_geocode(self, addresses: list, delay: float = 1.0) -> Dict[str, Optional[Dict]]:
        """
        Geokoduje wiele adresów z opóźnieniem (Nominatim wymaga max 1 req/s).
        
        Args:
            addresses: Lista adresów
            delay: Opóźnienie między requestami (sekundy)
            
        Returns:
            Dict {adres: {lat, lon}}
        """
        results = {}
        
        for i, address in enumerate(addresses):
            coords = self.geocode_address(address)
            results[address] = coords
            
            # Opóźnienie między requestami (polityka Nominatim)
            if i < len(addresses) - 1:
                time.sleep(delay)
        
        return results


# Testy jednostkowe
if __name__ == "__main__":
    geocoder = Geocoder(cache_file="test_geocoding_cache.json")
    
    test_addresses = [
        "Narutowicza 5",
        "Racławickie 14",
        "Plac Litewski 1",
        "Nieistniejąca Ulica 999"  # Test błędnego adresu
    ]
    
    print("🧪 Testy Geocoder:\n")
    for address in test_addresses:
        coords = geocoder.geocode_address(address)
        if coords:
            print(f"✅ {address} → {coords['lat']:.4f}, {coords['lon']:.4f}")
        else:
            print(f"❌ {address} → Nie znaleziono")
    
    print("\n📦 Cache zapisany w: test_geocoding_cache.json")

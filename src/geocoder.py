"""
Geocoder - zamiana adresów na współrzędne GPS
Używa Nominatim API (OpenStreetMap) + cache w JSON
+ walidacja czy adres jest w Lublinie (bounding box)
+ Fix #3 (2026-05-11): retry z transformacją do mianownika
"""

import json
import re
import time
from pathlib import Path
from typing import Optional, Dict, Tuple, List
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut, GeocoderServiceError

from atomic_json import atomic_write_json
# GeocoderRateLimited istnieje w nowszych geopy; fallback gdyby ktoś używał starszej wersji
try:
    from geopy.exc import GeocoderRateLimited
except ImportError:
    GeocoderRateLimited = None  # type: ignore

# Bounding box Lublina (~20x25 km z marginesem)
# Pokrywa centrum + wszystkie dzielnice + przedmieścia
LUBLIN_BBOX = {
    'min_lat': 51.18,   # Południowa granica (~3km od skraju)
    'max_lat': 51.30,   # Północna granica (~3km zapasu)
    'min_lon': 22.42,   # Zachodnia granica
    'max_lon': 22.68    # Wschodnia granica
}

# === FIX #3 (2026-05-11): Transformacja dopełniacz → mianownik ===
# Polskie nazwy ulic w ogłoszeniach często są w dopełniaczu ("przy Puławskiej")
# Nominatim szuka mianowników ("Puławska") - bez tej transformacji geokoder odrzuca
# ~40% prawdziwych ulic. Kolejność reguł istotna: dłuższe wzorce PRZED krótszymi.
NOMINATIVE_RULES = [
    # Końcówki -skiej / -ckiej i pochodne (Puławskiej → Puławska)
    (re.compile(r'owskiej$', re.IGNORECASE), 'owska'),
    (re.compile(r'ińskiej$', re.IGNORECASE), 'ińska'),
    (re.compile(r'yńskiej$', re.IGNORECASE), 'yńska'),
    (re.compile(r'eńskiej$', re.IGNORECASE), 'eńska'),
    # Specjalny przypadek: -dniej → -dnia (Zachodniej → Zachodnia, NIE → Zachodna)
    (re.compile(r'dniej$', re.IGNORECASE), 'dnia'),
    (re.compile(r'skiej$', re.IGNORECASE), 'ska'),
    (re.compile(r'ckiej$', re.IGNORECASE), 'cka'),
    (re.compile(r'kiej$', re.IGNORECASE), 'ka'),
    # Końcówki -owej / -nej (Spadowej → Spadowa, Pogodnej → Pogodna)
    (re.compile(r'owej$', re.IGNORECASE), 'owa'),
    (re.compile(r'nej$', re.IGNORECASE), 'na'),
    # Nazwiska męskie -ego (Wołodyjowskiego → Wołodyjowski, Dubieckiego → Dubiecki)
    (re.compile(r'wskiego$', re.IGNORECASE), 'wski'),
    (re.compile(r'ńskiego$', re.IGNORECASE), 'ński'),
    (re.compile(r'skiego$', re.IGNORECASE), 'ski'),
    (re.compile(r'ckiego$', re.IGNORECASE), 'cki'),
    (re.compile(r'iego$', re.IGNORECASE), 'i'),
    (re.compile(r'ego$', re.IGNORECASE), 'i'),
    # Liczba mnoga (Aleja Racławickich → Aleja Racławickie)
    (re.compile(r'ckich$', re.IGNORECASE), 'ckie'),
    (re.compile(r'skich$', re.IGNORECASE), 'skie'),
    (re.compile(r'ich$', re.IGNORECASE), 'ie'),
    # Generic -ej (Sympatycznej → Sympatyczna, Liliowej już złapane wyżej)
    (re.compile(r'ej$', re.IGNORECASE), 'a'),
]

# === FIX 2026-05-14 (P2b - fix B): drugorzędne warianty dla liczby mnogiej → pojedynczej ===
# Niektóre ulice Lublina mają formę kanoniczną w liczbie POJEDYNCZEJ żeńskiej:
#   - Kraśnicka (nie Kraśnickie)
#   - Nadbystrzycka (nie Nadbystrzyckie)  
#   - Nałkowska (nie Nałkowskie)
# Ale parser czasem wyciąga formę z opisu "okolice Kraśnickich/Nadbystrzyckich" (l.mn. dop.).
# Standardowy to_nominative transformuje to do l. mnogiej mianownika (Kraśnickie), które
# Nominatim nie zna. Te reguły dają DRUGI wariant - liczba pojedyncza żeńska.
# 
# UWAGA: są ulice z prawdziwą l. mnogą (Aleje Racławickie). Geocoder próbuje OBA warianty.
NOMINATIVE_VARIANT_RULES = [
    # Forma z -ckich → -cka (Kraśnickich → Kraśnicka, Nadbystrzyckich → Nadbystrzycka)
    (re.compile(r'ckich$', re.IGNORECASE), 'cka'),
    # Forma z -skich → -ska (Nałkowskich → Nałkowska, Lubomelskich → Lubomelska)
    (re.compile(r'skich$', re.IGNORECASE), 'ska'),
    # Forma z -ckie → -cka (Nadbystrzyckie → Nadbystrzycka)
    (re.compile(r'ckie$', re.IGNORECASE), 'cka'),
    # Forma z -skie → -ska (Wieniawskie → Wieniawska)
    (re.compile(r'skie$', re.IGNORECASE), 'ska'),
]

def to_nominative(address: str) -> str:
    """
    Transformuje polską nazwę ulicy z dopełniacza/innego przypadka do mianownika.
    Działa per-word - obsługuje też dwuczłonowe ("Aleja Racławickich" → "Aleja Racławickie")
    oraz adresy z numerem ("Puławskiej 10" → "Puławska 10").
    
    Każdy word jest transformowany niezależnie pierwszą pasującą regułą.
    """
    if not address:
        return address
    
    tokens = address.split()
    result = []
    for token in tokens:
        # Pomiń tokeny które są same cyframi/numerem domu (np. "10", "5a", "1/2")
        if re.match(r'^\d+[a-zA-Z]?(/\d+)?$', token):
            result.append(token)
            continue
        
        new_token = token
        for pattern, replacement in NOMINATIVE_RULES:
            if pattern.search(token):
                new_token = pattern.sub(replacement, token)
                break  # Pierwsza pasująca reguła wygrywa
        result.append(new_token)
    
    return ' '.join(result)


def to_nominative_singular_feminine(address: str) -> str:
    """
    Alternatywny mianownik dla nazw ulic w liczbie POJEDYNCZEJ ŻEŃSKIEJ.
    
    Stosuje NOMINATIVE_VARIANT_RULES per-word. Zwraca pusty string jeśli żadna
    reguła nie zadziałała (czyli adres nie ma formy zmieniającej się).
    
    Przykłady:
        "Kraśnickich"      → "Kraśnicka"
        "Aleja Kraśnickich" → "Aleja Kraśnicka"
        "Nadbystrzyckie"   → "Nadbystrzycka"
        "Racławickie"      → "Racławicka"   (UWAGA: ta forma NIE istnieje w Lublinie,
                                              ale Nominatim odrzuci ją i geocoder
                                              przejdzie do innych wariantów)
        "Lipowa"           → ""              (reguła nie zadziałała = brak alt. wariantu)
    
    Used by Geocoder jako dodatkowy wariant fallbacku (KROK 3.5).
    """
    if not address:
        return ''
    
    tokens = address.split()
    result = []
    any_change = False
    for token in tokens:
        if re.match(r'^\d+[a-zA-Z]?(/\d+)?$', token):
            result.append(token)
            continue
        
        new_token = token
        for pattern, replacement in NOMINATIVE_VARIANT_RULES:
            if pattern.search(token):
                new_token = pattern.sub(replacement, token)
                if new_token != token:
                    any_change = True
                break
        result.append(new_token)
    
    if not any_change:
        return ''  # Brak transformacji = brak alt. wariantu
    return ' '.join(result)


class Geocoder:
    # Ile dni cache None jest "świeże" — po tym czasie Nominatim jest odpytywany ponownie.
    # Chroni przed permanentnym zamrożeniem ulic które były niedostępne w Nominatim
    # chwilowo (timeout, rate-limit) lub których OSM jeszcze nie miał a teraz ma.
    NULL_CACHE_TTL_DAYS = 7

    def __init__(self, cache_file: str = None):
        if cache_file is None:
            try:
                from paths import GEOCODING_CACHE_JSON
                cache_file = GEOCODING_CACHE_JSON
            except ImportError:  # pragma: no cover
                cache_file = "../data/geocoding_cache.json"
        self.cache_file = Path(cache_file)
        self.cache = self._load_cache()
        # Osobny dict timestampów dla null entries: {address: epoch_float}
        # Przechowywany w cache JSON pod kluczem "__null_timestamps__"
        self._null_ts: Dict[str, float] = self.cache.pop('__null_timestamps__', {})
        self.geolocator = Nominatim(user_agent="sonar-mieszkaniowy-lublin/1.0")
        # FIX 2026-06-12: limit geokodowań per skan (MAX_NEW_GEOCODES w main.py).
        # main.py ustawiał tę flagę od dawna, ale geocoder nigdy jej nie czytał,
        # więc limit faktycznie NIE działał. Gdy True: tylko cache, zero zapytań
        # do Nominatim (i zero zapisów None do cache — patrz _try_nominatim).
        self._geocoding_limited = False
        # Stats dla Fix #3
        self._stats_nominative_hits = 0
        # Stats dla Fix 2026-05-14: ile razy fallback "sama ulica bez numeru" zadziałał
        self._stats_number_fallback_hits = 0

    def _null_is_expired(self, address: str) -> bool:
        """Zwraca True jeśli null-entry dla adresu jest starszy niż NULL_CACHE_TTL_DAYS."""
        ts = self._null_ts.get(address)
        if ts is None:
            # Brak timestampa = stary null (sprzed wdrożenia TTL) — traktuj jako wygasły
            return True
        age_days = (time.time() - ts) / 86400
        return age_days >= self.NULL_CACHE_TTL_DAYS

    def _set_null_cache(self, address: str):
        """Zapisuje null do cache wraz z timestampem."""
        self.cache[address] = None
        self._null_ts[address] = time.time()
        self._save_cache()

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
        """Zapisuje cache do pliku JSON (wraz z __null_timestamps__), atomowo."""
        # Wstrzyknij null_timestamps do kopii cache przed zapisem
        data_to_save = dict(self.cache)
        if self._null_ts:
            data_to_save['__null_timestamps__'] = self._null_ts
        # FIX 2026-06-12: atomowy zapis (tmp + os.replace) — przerwany zapis
        # nie zostawia uciętego pliku cache
        atomic_write_json(self.cache_file, data_to_save)
    
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
    
    def geocode_address(self, address: str, max_retries: int = 3, return_meta: bool = False):
        """
        Geokoduje adres na współrzędne GPS.
        
        Strategia:
        1. Sprawdź cache pod oryginalnym kluczem
        2. Spróbuj Nominatim z oryginalnym adresem
        3. Jeśli fail, przekształć do mianownika ("Puławskiej" → "Puławska") i ponów
        4. Jeśli fail, retry z liczbą mnogą/poj. (Aleja ↔ Aleje)
        5. Fix 2026-05-14: jeśli adres ma numer i dotąd brak wyniku, spróbuj samej ulicy
           bez numeru. Zwraca koordynaty samej ulicy + flagę fallback w meta.
        6. Cache zapisuje wynik pod ORYGINALNYM kluczem (żeby był idempotentny).
        
        Args:
            address: Adres do geokodowania (np. "Narutowicza 5" lub "Puławskiej")
            max_retries: Maksymalna liczba prób per query
            return_meta: Jeśli True, zwraca tupla (coords, meta_dict). Domyślnie zachowuje
                wsteczną kompatybilność i zwraca sam coords (lub None).
        
        Returns:
            Jeśli return_meta=False (domyślnie): Dict z lat, lon lub None.
            Jeśli return_meta=True: tupla (coords, meta) gdzie meta to dict:
                - 'number_fallback': bool — True jeśli zwrócono koordynaty samej ulicy
                  zamiast adresu z numerem (caller powinien obniżyć precision do street_only)
                - 'cache_hit': bool — True jeśli wynik pochodzi z cache (bez Nominatim)
        """
        coords, meta = self._geocode_with_meta(address, max_retries)
        if return_meta:
            return coords, meta
        return coords

    def geocode_with_alternatives(self, address_data: Dict, max_retries: int = 3) -> Optional[Tuple[Dict, Dict]]:
        """
        Geokoduje adres z fallbackami: próbuje 'full' z address_data, potem każdy z 'alternatives',
        pierwszy który trafi w bbox Lublina wygrywa.
        
        Dodane w mieszkaniowym (2026-05-15) bo bez słów typu 'mieszkanie', 'piętro',
        'apartament' w EXCLUDED_WORDS parser address_parser.extract_address() łapie
        pseudo-adresy typu 'Mieszkanie 3' jako pierwszego kandydata. Bez tego fallbacku
        takie oferty by nigdy nie były geokodowane.
        
        Args:
            address_data: Dict z polami 'street', 'number', 'full' oraz opcjonalnie
                          'alternatives' (lista dictów z analogicznymi polami).
                          Stary format (bez 'alternatives') też jest akceptowany —
                          traktowany jak alternatives=[].
            max_retries: Maksymalna liczba prób per adres
        
        Returns:
            None jeśli żaden kandydat nie geokoduje się do bbox Lublina.
            W przeciwnym razie tupla (coords, used_address) gdzie:
              - coords: Dict z 'lat', 'lon'
              - used_address: Dict z 'street', 'number', 'full', 'meta' — który KONKRETNIE
                kandydat zwyciężył. 'meta' zawiera 'number_fallback' i 'cache_hit'.
        """
        if not address_data or not address_data.get('full'):
            return None
        
        # Lista wszystkich kandydatów: główny + alternatywy
        candidates: List[Dict] = [{
            'street': address_data.get('street', ''),
            'number': address_data.get('number', ''),
            'full': address_data['full'],
        }]
        for alt in (address_data.get('alternatives') or []):
            if alt.get('full'):
                candidates.append({
                    'street': alt.get('street', ''),
                    'number': alt.get('number', ''),
                    'full': alt['full'],
                })
        
        # Próbuj kandydatów po kolei. is_in_lublin sprawdza bbox - naturalna walidacja
        # czy adres faktycznie istnieje w Lublinie (Nominatim może zwrócić ulicę z innego
        # miasta o tej samej nazwie).
        for i, cand in enumerate(candidates):
            coords, meta = self._geocode_with_meta(cand['full'], max_retries)
            if coords and self.is_in_lublin(coords):
                if i > 0:
                    print(f"      ✓ Geokodowanie z alternatywy #{i}: '{cand['full']}' "
                          f"(główny '{candidates[0]['full']}' nie trafił w Lublin)")
                return coords, {
                    'street': cand['street'],
                    'number': cand['number'],
                    'full': cand['full'],
                    'meta': meta,
                }
        
        return None

    def _geocode_with_meta(self, address: str, max_retries: int = 3):
        """Implementacja geokodowania, zawsze zwraca (coords, meta)."""
        meta = {'number_fallback': False, 'cache_hit': False}
        
        if not address:
            return None, meta
        
        # Sprawdzamy cache - oryginalny klucz
        if address in self.cache:
            cached_value = self.cache[address]

            # === FIX #6 (2026-05-13): cache-poisoning bypass ===
            # Jeśli w cache mamy None ale transformacja mianownika daje inny string,
            # NIE zwracaj None z cache - spróbuj mianownik (może być w cache jako koordynaty,
            # albo Nominatim go znajdzie). Bez tego cache zatruty przed Fix #3 pozostaje
            # martwy mimo że mianownik działa.
            if cached_value is None:
                nominative_check = to_nominative(address)
                if nominative_check != address:
                    # Mianownik się różni - sprawdź czy jest w cache z koordynatami
                    if nominative_check in self.cache and self.cache[nominative_check] is not None:
                        coords = self.cache[nominative_check]
                        print(f"      ♻️  Bypass zatrutego cache '{address}' → mianownik '{nominative_check}' jest w cache")
                        # Zaktualizuj cache oryginału żeby następnym razem hit był natychmiastowy
                        self.cache[address] = coords
                        self._save_cache()
                        self._stats_nominative_hits += 1
                        meta['cache_hit'] = True
                        return coords, meta
                # FIX 2026-06-12: TTL nulla obowiązuje NIEZALEŻNIE od tego czy mianownik
                # się różni. Wcześniej adres z odmienialną nazwą (nominative != address)
                # nigdy nie korzystał z TTL — przy każdym skanie odpytywał Nominatim live
                # (oryginał + mianownik), a finalne _set_null_cache odświeżało timestamp,
                # więc null nigdy nie wygasał "naturalnie".
                if self._null_is_expired(address):
                    print(f"      ♻️  Wygasły null-cache dla '{address}' (>{self.NULL_CACHE_TTL_DAYS}d) — retry Nominatim")
                    del self.cache[address]
                    # Nie usuwamy z _null_ts — _set_null_cache zaktualizuje timestamp jeśli nadal None
                # Jeśli null świeży: dalszy flow działa w trybie cache-only
                # (live_allowed=False poniżej) — fallbacki przez cache nadal działają.
            else:
                # Cache ma koordynaty - zwróć je
                meta['cache_hit'] = True
                return cached_value, meta

        # FIX 2026-06-12: świeży (niewygasły) null = tryb cache-only dla tego adresu.
        # Poprzedni skan przeszedł już CAŁĄ ścieżkę (oryginał + mianownik + warianty)
        # i nic nie znalazł — w oknie TTL nie powtarzamy zapytań live, ale nadal
        # sprawdzamy cache wariantów (mogły dojść z innych ofert).
        live_allowed = not (address in self.cache and self.cache[address] is None)

        # === KROK 1: Próba z oryginalnym adresem ===
        coords = None
        if live_allowed:
            try:
                coords = self._try_nominatim(address, max_retries=max_retries)
            except (GeocoderTimedOut, GeocoderServiceError) as e:
                # Tymczasowy błąd (rate-limit, timeout, 5xx) - NIE zapisuj None do cache
                print(f"      ⏸️  Tymczasowy błąd Nominatim dla '{address}': {type(e).__name__}")
                return None, meta

            if coords is not None:
                self.cache[address] = coords
                self._save_cache()
                return coords, meta
        
        # === KROK 2 (Fix #3): Retry z transformacją do mianownika ===
        nominative = to_nominative(address)
        if nominative != address:
            # Tylko jeśli transformacja faktycznie coś zmieniła
            print(f"      🔄 Retry z mianownikiem: '{address}' → '{nominative}'")
            
            # Sprawdź czy mianownik jest w cache (możliwe że już go geokodowaliśmy)
            if nominative in self.cache and self.cache[nominative] is not None:
                coords = self.cache[nominative]
                print(f"      ✅ Trafiony cache mianownika: {nominative}")
                self.cache[address] = coords  # Zapisz pod oryginalnym też
                self._save_cache()
                self._stats_nominative_hits += 1
                return coords, meta

            if live_allowed:
                try:
                    coords = self._try_nominatim(nominative, max_retries=max_retries)
                except (GeocoderTimedOut, GeocoderServiceError) as e:
                    # Tymczasowy błąd przy mianowniku - NIE zapisuj None do cache
                    print(f"      ⏸️  Tymczasowy błąd Nominatim dla mianownika '{nominative}': {type(e).__name__}")
                    return None, meta

                if coords is not None:
                    print(f"      ✅ Mianownik znaleziony: {nominative}")
                    # Cache pod OBA klucze
                    self.cache[address] = coords
                    self.cache[nominative] = coords
                    self._save_cache()
                    self._stats_nominative_hits += 1
                    return coords, meta
        
        # === KROK 3 (Fix 2026-05-14): retry z liczbą mnogą Aleja ↔ Aleje ===
        # W Lublinie są ulice w liczbie mnogiej: "Aleje Racławickie", "Aleje 1000-lecia",
        # "Aleje Solidarności" itd. Parser standardowo robi "Aleja" (liczba poj.), więc
        # Nominatim nie znajduje. Próbujemy z "Aleje".
        # Analogicznie odwrotnie - jeśli ktoś napisał "Aleje X" a to jest "Aleja X".
        plural_variants = []
        # Wybierz mianownik (jeśli istnieje) albo oryginał
        candidate = nominative if nominative != address else address
        if candidate.startswith('Aleja '):
            plural_variants.append('Aleje ' + candidate[len('Aleja '):])
        elif candidate.startswith('Aleje '):
            plural_variants.append('Aleja ' + candidate[len('Aleje '):])
        
        for variant in plural_variants:
            print(f"      🔄 Retry liczba mnoga/poj.: '{address}' → '{variant}'")
            
            # Cache hit?
            if variant in self.cache and self.cache[variant] is not None:
                coords = self.cache[variant]
                print(f"      ✅ Trafiony cache wariantu: {variant}")
                self.cache[address] = coords
                self._save_cache()
                return coords, meta

            if not live_allowed:
                continue

            try:
                coords = self._try_nominatim(variant, max_retries=max_retries)
            except (GeocoderTimedOut, GeocoderServiceError) as e:
                print(f"      ⏸️  Tymczasowy błąd Nominatim dla '{variant}': {type(e).__name__}")
                return None, meta

            if coords is not None:
                print(f"      ✅ Wariant znaleziony: {variant}")
                self.cache[address] = coords
                self.cache[variant] = coords
                self._save_cache()
                return coords, meta
        
        # === KROK 3.5 (Fix 2026-05-14, P2b): wariant liczba pojedyncza żeńska ===
        # Niektóre ulice Lublina mają formę kanoniczną w liczbie POJEDYNCZEJ żeńskiej:
        # Kraśnicka, Nadbystrzycka, Nałkowska. Parser z opisów typu "okolice Kraśnickich"
        # daje "Kraśnickich" (l.mn. dop.), standardowy to_nominative robi "Kraśnickie",
        # ale Nominatim zna tylko "Kraśnicka". Próbujemy obu form.
        # Działa też dla "Nadbystrzyckie" → "Nadbystrzycka" (gdy parser wyciągnął już l.mn.
        # mianownik z opisu typu "ul. Nadbystrzyckie").
        # 
        # WAŻNE: jeśli oryginał i nominative już wyczerpały te warianty, pomijamy.
        singular_fem_variants = []
        for source in [address, nominative]:
            variant = to_nominative_singular_feminine(source)
            if variant and variant not in singular_fem_variants and variant != address and variant != nominative:
                singular_fem_variants.append(variant)
        
        for variant in singular_fem_variants:
            print(f"      🔄 Retry l. poj. żeńska: '{address}' → '{variant}'")
            
            if variant in self.cache and self.cache[variant] is not None:
                coords = self.cache[variant]
                print(f"      ✅ Trafiony cache wariantu: {variant}")
                self.cache[address] = coords
                self._save_cache()
                return coords, meta
            
            if variant in self.cache and self.cache[variant] is None:
                continue  # Już wiemy że Nominatim go nie zna

            if not live_allowed:
                continue

            try:
                coords = self._try_nominatim(variant, max_retries=max_retries)
            except (GeocoderTimedOut, GeocoderServiceError) as e:
                print(f"      ⏸️  Tymczasowy błąd Nominatim dla '{variant}': {type(e).__name__}")
                return None, meta

            if coords is not None:
                print(f"      ✅ Wariant l. poj. ż. znaleziony: {variant}")
                self.cache[address] = coords
                self.cache[variant] = coords
                self._save_cache()
                return coords, meta
            else:
                # Cache None dla negatywnego wyniku — ale tylko pod kluczem wariantu
                self._set_null_cache(variant)
        
        # === KROK 4 (Fix 2026-05-14): fallback "sama ulica bez numeru" ===
        # Jeśli adres ma numer i wszystkie powyższe podejścia zawiodły, spróbuj samej ulicy.
        # Nominatim często nie ma konkretnego numeru w bazie (np. "Narutowicza 38" — None,
        # ale "Narutowicza" — znajduje się ulica). Wracamy koordynaty samej ulicy i flagę
        # number_fallback=True, żeby caller obniżył precision do 'street_only'.
        # 
        # WAŻNE: NIE zapisujemy wyniku pod cache[address] - bez tego utracilibyśmy info
        # o fallbacku przy kolejnym wywołaniu (cache zwracałby koordynaty samej ulicy
        # bez flagi number_fallback, caller traktowałby je jako precision=exact).
        # Zamiast tego cache[street_only] zostaje uzupełnione (jeśli to świeży Nominatim),
        # więc kolejny call dla tej samej oferty (z numerem) i tak zrobi tylko 1 cache lookup
        # dla street_only — co jest bardzo szybkie.
        # 
        # Strategia: weź WSZYSTKIE warianty (oryginał, mianownik, liczba mnoga/poj.) i dla
        # każdego usuń ostatni token jeśli wygląda na numer domu. Próbuj każdy.
        # FIX P2b: dorzucamy też singular_fem_variants (np. "Nadbystrzycka 38")
        all_variant_sources = list(plural_variants) + list(singular_fem_variants)
        street_only_candidates = self._strip_number_variants(address, nominative, all_variant_sources)
        for street_only in street_only_candidates:
            # Cache hit (z koordynatami)?
            if street_only in self.cache and self.cache[street_only] is not None:
                coords = self.cache[street_only]
                print(f"      🎯 Fallback 'sama ulica': '{address}' → '{street_only}' (z cache)")
                self._stats_number_fallback_hits += 1
                meta['number_fallback'] = True
                return coords, meta
            
            # Cache None? Pomiń próbę Nominatim (już wiemy że nie znajdzie)
            if street_only in self.cache and self.cache[street_only] is None:
                continue

            if not live_allowed:
                continue

            # Spróbuj Nominatim z samą ulicą
            print(f"      🎯 Fallback 'sama ulica': '{address}' → próbuję '{street_only}'")
            try:
                coords = self._try_nominatim(street_only, max_retries=max_retries)
            except (GeocoderTimedOut, GeocoderServiceError) as e:
                print(f"      ⏸️  Tymczasowy błąd Nominatim dla '{street_only}': {type(e).__name__}")
                # Nie cache'ujemy None na tymczasowy błąd; idź do następnego wariantu
                continue
            
            if coords is not None:
                print(f"      ✅ Fallback znaleziony: {street_only}")
                # Cache POD KLUCZEM samej ulicy (żeby inne oferty z tej ulicy też trafiały).
                # NIE zapisujemy pod cache[address] - patrz komentarz wyżej.
                self.cache[street_only] = coords
                self._save_cache()
                self._stats_number_fallback_hits += 1
                meta['number_fallback'] = True
                return coords, meta
            else:
                # Cache None dla wariantu samej ulicy (np. literówka w nazwie)
                self._set_null_cache(street_only)
        
        # Wszystkie podejścia zawiodły (faktyczne None od Nominatim) - cache jako None.
        # FIX 2026-06-12: tylko gdy faktycznie pytaliśmy live — w trybie cache-only
        # NIE odświeżamy timestampu nulla (inaczej TTL nigdy by nie wygasł).
        if live_allowed:
            self._set_null_cache(address)
        return None, meta
    
    @staticmethod
    def _strip_number_variants(address: str, nominative: str, plural_variants: list) -> list:
        """
        Zwraca listę wariantów adresu BEZ numeru domu (dla fallbacku 'sama ulica').
        
        Filtruje:
        - duplikaty
        - warianty identyczne z oryginałem (numer nie był usuwany — brak fallbacku do zrobienia)
        - puste wyniki (gdy adres był jednowyrazowy)
        
        Args:
            address: oryginalny adres
            nominative: po transformacji do mianownika
            plural_variants: lista wariantów Aleja↔Aleje
        
        Returns:
            Lista unikalnych wariantów adresu bez numeru, np. ["Narutowicza", "Aleja Racławickie"]
        """
        all_variants = [address, nominative] + list(plural_variants)
        # Usuń duplikaty zachowując kolejność
        seen = set()
        unique_variants = []
        for v in all_variants:
            if v and v not in seen:
                seen.add(v)
                unique_variants.append(v)
        
        result = []
        # Wzorzec numeru domu: cyfry opcjonalnie + litera + opcjonalnie /N
        # Przykłady: "5", "10A", "80a", "12/5", "5A/11"
        number_pattern = re.compile(r'^\d+[a-zA-Z]?(?:/\d+)?$')
        
        for variant in unique_variants:
            tokens = variant.split()
            # Adres musi mieć min 2 tokeny żeby było co odciąć
            if len(tokens) < 2:
                continue
            # Ostatni token musi wyglądać na numer domu
            if not number_pattern.match(tokens[-1]):
                continue
            stripped = ' '.join(tokens[:-1])
            if stripped and stripped not in seen:
                seen.add(stripped)
                result.append(stripped)
        
        return result
    
    def _try_nominatim(self, address: str, max_retries: int = 3) -> Optional[Dict[str, float]]:
        """
        Pojedyncza próba zapytania do Nominatim (bez logiki retry mianownikiem).
        Zwraca coords lub None.
        
        Raises:
            GeocoderRateLimited / GeocoderServiceError (429): tymczasowy błąd serwera,
                NIE zapisuj wyniku do cache - propagujemy żeby caller obsłużył.
        """
        # FIX 2026-06-12: tryb limited (MAX_NEW_GEOCODES) — nie odpytuj Nominatim.
        # Rzucamy GeocoderServiceError, bo wszystkie miejsca wywołania traktują go
        # jak błąd tymczasowy: zwracają None BEZ zapisu None do cache, więc adres
        # zostanie normalnie zgeokodowany w następnym skanie.
        if self._geocoding_limited:
            raise GeocoderServiceError('limit geokodowań osiągnięty (MAX_NEW_GEOCODES)')

        # Pełny adres z miastem
        full_address = f"{address}, Lublin, Poland"

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
                        print(f"      ⚠️ Odrzucono {address} - poza Lublinem (lat={coords['lat']:.4f}, lon={coords['lon']:.4f})")
                        return None
                    
                    return coords
                else:
                    # Nie znaleziono - prawdziwy negatywny wynik
                    return None
                    
            except GeocoderTimedOut:
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)  # Exponential backoff
                    continue
                else:
                    # Timeout - traktuj jak tymczasowy błąd, NIE zapisuj None do cache
                    raise
                    
            except GeocoderServiceError as e:
                # FIX 2026-05-13: rozróżnij rate-limit (429) od innych błędów serwera
                # Rate-limit jest TYMCZASOWY - nie zapisuj wyniku do cache.
                # Innych błędów serwera też nie cachuj - mogą minąć przy następnym scanie.
                err_str = str(e).lower()
                is_rate_limit = (
                    '429' in err_str
                    or 'rate' in err_str
                    or 'quota' in err_str
                    or (GeocoderRateLimited is not None and isinstance(e, GeocoderRateLimited))
                )
                if is_rate_limit:
                    print(f"      ⏸️  Rate limit Nominatim dla '{address}' - nie cachuję None")
                    raise  # Propaguj, caller obsłuży
                # Inne błędy serwera też propaguj - lepiej None than cache-poisoning
                raise
        
        return None


# Testy jednostkowe
if __name__ == "__main__":
    # ===== FIX 2026-05-14: Testy _strip_number_variants =====
    print("🧪 FIX 2026-05-14 — _strip_number_variants:\n")
    strip_cases = [
        # (address, nominative, plural_variants, expected_result)
        ("Narutowicza 38", "Narutowicza 38", [], ["Narutowicza"]),
        ("Lipowej 10", "Lipowa 10", [], ["Lipowej", "Lipowa"]),
        ("Aleja Racławickie 6", "Aleja Racławickie 6", ["Aleje Racławickie 6"],
         ["Aleja Racławickie", "Aleje Racławickie"]),
        # Bez numeru — nic do odciąć
        ("Narutowicza", "Narutowicza", [], []),
        # Tylko jeden token + numer — zwróci ulicę (2 tokeny więc len(tokens)>=2)
        ("Centrum 5", "Centrum 5", [], ["Centrum"]),
        # Numer z literą
        ("Wojciechowska 5A", "Wojciechowska 5A", [], ["Wojciechowska"]),
        # Numer z lokalem
        ("Lipowa 14/2", "Lipowa 14/2", [], ["Lipowa"]),
        # Duplikaty
        ("Lipowa 10", "Lipowa 10", ["Lipowa 10"], ["Lipowa"]),
        # Pusty
        ("", "", [], []),
    ]
    strip_pass = 0
    strip_fail = 0
    for addr, nom, plurals, expected in strip_cases:
        actual = Geocoder._strip_number_variants(addr, nom, plurals)
        ok = actual == expected
        status = "✅" if ok else "❌"
        if ok:
            strip_pass += 1
        else:
            strip_fail += 1
        print(f"{status} ({addr!r}, {nom!r}, {plurals}) → {actual}")
        if not ok:
            print(f"   Oczekiwano: {expected}")
    print(f"\n📊 _strip_number_variants: {strip_pass} OK / {strip_fail} FAIL")

    # ===== FIX 2026-05-14: Testy fallbacku przez cache =====
    print("\n🧪 FIX 2026-05-14 — geocode_address z return_meta i fallback przez cache:\n")
    import tempfile, json as _json, os as _os
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as tf:
        cache_data = {
            "Narutowicza": {"lat": 51.2458251, "lon": 22.5604385},  # ma koordy
            "Narutowicza 38": None,  # zatruty - tu fallback powinien zadziałać
            "Lipowa 14": {"lat": 51.2342, "lon": 22.5601},  # ma koordy, exact
        }
        _json.dump(cache_data, tf)
        cache_path = tf.name

    test_geo = Geocoder(cache_file=cache_path)
    
    fallback_test_cases = [
        # (address, expected_coords_obtained, expected_meta_subset)
        ("Lipowa 14", True, {"cache_hit": True, "number_fallback": False}),
        ("Narutowicza 38", True, {"cache_hit": False, "number_fallback": True}),
        ("Narutowicza", True, {"cache_hit": True, "number_fallback": False}),
    ]
    
    fb_pass = 0
    fb_fail = 0
    for addr, expected_has_coords, expected_meta in fallback_test_cases:
        coords, meta = test_geo.geocode_address(addr, return_meta=True)
        ok_coords = (coords is not None) == expected_has_coords
        ok_meta = all(meta.get(k) == v for k, v in expected_meta.items())
        ok = ok_coords and ok_meta
        status = "✅" if ok else "❌"
        if ok: fb_pass += 1
        else: fb_fail += 1
        print(f"{status} {addr!r} → coords_present={coords is not None}, meta={meta}")
        if not ok:
            print(f"   Oczekiwano: has_coords={expected_has_coords}, meta zawiera {expected_meta}")
    print(f"\n📊 Fallback meta: {fb_pass} OK / {fb_fail} FAIL")
    
    # Sprawdź czy fallback NIE zatruł cache pod kluczem oryginału
    print("\n🧪 Test: fallback NIE zapisuje koord pod oryginalnym kluczem:")
    if test_geo.cache.get('Narutowicza 38') is None:
        print("✅ cache[Narutowicza 38] = None (poprawnie - fallback nie zatruwa)")
        fb_pass += 1
    else:
        print(f"❌ cache[Narutowicza 38] = {test_geo.cache.get('Narutowicza 38')} (powinno być None)")
        fb_fail += 1
    
    # Sprawdź licznik fallbacków
    print("\n🧪 Test: licznik _stats_number_fallback_hits działa:")
    if test_geo._stats_number_fallback_hits >= 1:
        print(f"✅ _stats_number_fallback_hits = {test_geo._stats_number_fallback_hits}")
        fb_pass += 1
    else:
        print(f"❌ _stats_number_fallback_hits = {test_geo._stats_number_fallback_hits} (powinno być >= 1)")
        fb_fail += 1
    
    # Wsteczna kompatybilność: bez return_meta zachowuje stary kontrakt
    print("\n🧪 Test: wsteczna kompatybilność (bez return_meta):")
    coords_legacy = test_geo.geocode_address("Lipowa 14")
    if isinstance(coords_legacy, dict) and 'lat' in coords_legacy:
        print(f"✅ Bez return_meta zwraca samo coords dict: {coords_legacy}")
        fb_pass += 1
    else:
        print(f"❌ Bez return_meta zwraca: {coords_legacy}")
        fb_fail += 1
    
    _os.unlink(cache_path)

    # ===== FIX 2026-05-14 (P2b): Testy to_nominative_singular_feminine =====
    print("\n🧪 FIX 2026-05-14 (P2b) — to_nominative_singular_feminine:\n")
    fem_cases = [
        # Liczba mnoga dop. → liczba pojedyncza ż.
        ('Kraśnickich', 'Kraśnicka'),
        ('Aleja Kraśnickich', 'Aleja Kraśnicka'),
        ('Nadbystrzyckich', 'Nadbystrzycka'),
        ('Nałkowskich', 'Nałkowska'),
        ('Osiedle Nałkowskich', 'Osiedle Nałkowska'),
        # Liczba mnoga mianownik → liczba pojedyncza ż.
        ('Nadbystrzyckie', 'Nadbystrzycka'),
        ('Racławickie', 'Racławicka'),  # forma nie istniejąca, ale funkcja zwraca, Nominatim odrzuci
        # Brak transformacji = pusty string
        ('Lipowa', ''),
        ('Narutowicza', ''),
        ('Plac Litewski', ''),
        ('', ''),
        # Z numerem (numer powinien zostać)
        ('Kraśnickich 5', 'Kraśnicka 5'),
        ('Nadbystrzyckie 10A', 'Nadbystrzycka 10A'),
    ]
    fem_pass = 0
    fem_fail = 0
    for inp, expected in fem_cases:
        actual = to_nominative_singular_feminine(inp)
        ok = "✅" if actual == expected else "❌"
        if actual == expected: fem_pass += 1
        else: fem_fail += 1
        print(f"{ok} {inp!r} → {actual!r}")
        if actual != expected:
            print(f"   Oczekiwano: {expected!r}")
    print(f"\n📊 to_nominative_singular_feminine: {fem_pass} OK / {fem_fail} FAIL")

    # Test flow: cache-based fallback w geocode_address (bez Nominatim live)
    print("\n🧪 FIX 2026-05-14 (P2b) — fallback KROK 3.5 przez cache:\n")
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as tf:
        cache_data_p2b = {
            "Kraśnicka": {"lat": 51.2426, "lon": 22.5068},
            "Nadbystrzycka": {"lat": 51.2331, "lon": 22.5397},
            "Aleja Kraśnickich": None,
            "Aleja Kraśnickie": None,
            "Aleje Kraśnickie": None,
            "Nadbystrzyckie": None,
        }
        _json.dump(cache_data_p2b, tf)
        cache_path_p2b = tf.name

    test_geo_p2b = Geocoder(cache_file=cache_path_p2b)
    
    p2b_cases = [
        # (address, expected_has_coords)
        ('Aleja Kraśnickich', True),   # przez Aleja Kraśnicka
        ('Nadbystrzyckie', True),       # przez Nadbystrzycka
    ]
    p2b_pass = 0
    p2b_fail = 0
    for addr, expected_has_coords in p2b_cases:
        coords = test_geo_p2b.geocode_address(addr)
        ok = (coords is not None) == expected_has_coords
        status = "✅" if ok else "❌"
        if ok: p2b_pass += 1
        else: p2b_fail += 1
        print(f"{status} {addr!r} → coords={coords}")
    print(f"\n📊 KROK 3.5 flow: {p2b_pass} OK / {p2b_fail} FAIL")
    
    _os.unlink(cache_path_p2b)

    print(f"\n{'='*60}")
    total_pass = strip_pass + fb_pass + fem_pass + p2b_pass
    total_fail = strip_fail + fb_fail + fem_fail + p2b_fail
    print(f"📊 ŁĄCZNIE Fix 2026-05-14 (geocoder): {total_pass} OK / {total_fail} FAIL")
    print(f"{'='*60}")

    # ===== Oryginalne testy (zakomentowane - wymagają Nominatim API live) =====
    # Te testy wykonują prawdziwe zapytania do Nominatim i tworzą test_geocoding_cache.json.
    # Uruchamiaj manualnie tylko przy potrzebie testów end-to-end.
    # 
    # geocoder = Geocoder(cache_file="test_geocoding_cache.json")
    # test_addresses = ["Narutowicza 5", "Racławickie 14", "Plac Litewski 1"]
    # for address in test_addresses:
    #     coords = geocoder.geocode_address(address)
    #     print(f"  {address} → {coords}")

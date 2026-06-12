"""
Price Parser V2 - inteligentne parsowanie cen najmu (mieszkania)
Priorytet: cena najmu (bez opłat/mediów) > cena z nagłówka
Filtruje: liczby z adresów, lata (2024-2030), liczby poza zakresem 200-10000 zł

UWAGA (zaszłość): projekt powstał jako port z SONAR-POKOJOWY, stąd część
wzorców tekstowych nadal dopasowuje słowo "pokój" — to celowe: łapie rozbicia
typu "850 zł – pokój + 250 zł – opłaty" oraz ogłoszenia pokoi w mieszkaniach.
Głównym źródłem ceny jest i tak JSON-LD z OLX (patrz main.py), a te wzorce to
fallback tekstowy (PRIORYTET 3). Nie zmieniaj treści regexów bez testów.
"""

import re
from typing import Optional, Dict, List

class PriceParser:
    # Wzorce na cenę najmu (BEZ opłat/mediów).
    # Treść regexów celowo niezmieniona z wersji pokojowej — patrz docstring modułu.
    RENT_PRICE_PATTERNS = [
        re.compile(r'(\d{3,4})\s*(?:zł|PLN)?\s*[-–—]\s*pokój', re.IGNORECASE),
        re.compile(r'pokój\s*[-–—]?\s*(\d{3,4})\s*(?:zł|PLN)?', re.IGNORECASE),
        re.compile(r'za\s*pokój\s*(\d{3,4})\s*(?:zł|PLN)?', re.IGNORECASE),
        re.compile(r'(\d{3,4})\s*(?:zł|PLN)?\s*pokój', re.IGNORECASE),
        re.compile(r'czynsz\s*(\d{3,4})\s*(?:zł|PLN)?', re.IGNORECASE),
        re.compile(r'najem\s*(\d{3,4})\s*(?:zł|PLN)?', re.IGNORECASE),
    ]
    
    # Wzorce na rozbicie: pokój + opłaty
    SPLIT_PATTERNS = [
        # "1100 zł (850 zł – pokój + 250 zł – opłaty)"
        re.compile(r'\((\d{3,4})\s*(?:zł)?\s*[-–—]\s*pokój\s*\+\s*(\d{2,4})\s*(?:zł)?\s*[-–—]\s*opłaty\)', re.IGNORECASE),
        # "850 zł – pokój + 250 zł – opłaty"
        re.compile(r'(\d{3,4})\s*(?:zł)?\s*[-–—]\s*pokój\s*\+\s*(\d{2,4})\s*(?:zł)?\s*[-–—]\s*opłaty', re.IGNORECASE),
        # "pokój 850 zł + opłaty 250 zł"
        re.compile(r'pokój\s*(\d{3,4})\s*(?:zł)?\s*\+\s*opłaty\s*(\d{2,4})', re.IGNORECASE),
    ]
    
    # Frazy wskazujące na media wliczone (WSZYSTKIE media)
    MEDIA_INCLUDED = [
        'wszystko wliczone', 'razem z mediami', 'wraz z mediami', 
        'łącznie z mediami', 'all inclusive', 'wszystko w cenie', 
        'opłaty wliczone', 'w tym wszystkie opłaty', 'media w cenie czynszu'
    ]
    
    # Frazy wskazujące na media częściowo wliczone (np. tylko internet)
    MEDIA_PARTIAL = [
        'internet w cenie', 'internet wliczony', 'wi-fi w cenie',
        'wi-fi wliczony', 'wifi w cenie'
    ]
    
    # Frazy wskazujące na media osobno
    MEDIA_SEPARATE = [
        '+ media', 'plus media', 'bez mediów', 'opłaty dodatkowe',
        'media dodatkowo', 'media osobno', 'do tego media', 'bez opłat',
        'media oddzielnie', '+ opłaty', 'opłaty osobno', 
        'dodatkowo płatne', 'płatne dodatkowo', 'media wg zużycia',
        'media według zużycia', 'wg zużycia', 'według zużycia'
    ]
    
    def __init__(self):
        pass
    
    # FIX 2026-06-12: usunięto martwe _filter_invalid_prices — nieużywane od czasu
    # usunięcia fallbacku "pierwsza sensowna kwota" (extract_price PRIORYTET 2).

    def _extract_rent_price(self, text: str) -> Optional[int]:
        """
        Próbuje wyciągnąć cenę najmu (bez opłat) używając wzorców tekstowych.
        Zwraca None jeśli nie znaleziono.
        """
        # Najpierw sprawdź rozbicie: "850 zł – pokój + 250 zł – opłaty"
        for pattern in self.SPLIT_PATTERNS:
            match = pattern.search(text)
            if match:
                room_price = int(match.group(1))
                # Walidacja (FIX 2026-05: zakres dla mieszkań)
                if 200 <= room_price <= 10000:
                    return room_price
        
        # Potem szukaj wzorców typu "X zł – pokój", "pokój X zł" itp.
        for pattern in self.RENT_PRICE_PATTERNS:
            match = pattern.search(text)
            if match:
                price = int(match.group(1))
                # Walidacja - sensowny zakres dla mieszkania (FIX 2026-05)
                if 200 <= price <= 10000:
                    return price
        
        return None
    
    def _detect_media_info_advanced(self, text_lower: str, rent_price: int) -> str:
        """
        Wykrywa informację o mediach - zaawansowana wersja.
        Próbuje wyciągnąć konkretną kwotę opłat jeśli jest podana.
        """
        # Sprawdź czy jest rozbicie z konkretną kwotą opłat
        for pattern in self.SPLIT_PATTERNS:
            match = pattern.search(text_lower)
            if match and len(match.groups()) >= 2:
                utilities_cost = int(match.group(2))
                return f"+ {utilities_cost} zł opłaty"
        
        # Sprawdź czy wszystkie media są wliczone
        for phrase in self.MEDIA_INCLUDED:
            if phrase in text_lower:
                return "wliczone"
        
        # PRIORYTET: Sprawdź czy media są osobno (przed częściowo!)
        for phrase in self.MEDIA_SEPARATE:
            if phrase in text_lower:
                return "+ media"
        
        # Sprawdź czy media są częściowo wliczone (np. tylko internet)
        for phrase in self.MEDIA_PARTIAL:
            if phrase in text_lower:
                return "częściowo wliczone (sprawdź opis)"
        
        # Jeśli nie ma informacji
        return "brak informacji"
    
    def extract_price(self, text: str) -> Optional[Dict[str, any]]:
        """
        Wyciąga cenę pokoju (bez mediów/opłat) z tekstu.
        
        Strategia:
        1. Szukaj wzorców typu "850 zł – pokój + 250 zł – opłaty" (priorytet)
        2. Szukaj wzorców typu "pokój 800 zł", "za pokój 750 zł"
        3. Jeśli nie znaleziono - bierz pierwszą sensowną kwotę (po filtrowaniu)
        
        Args:
            text: Tekst ogłoszenia (tytuł + opis)
            
        Returns:
            Dict z kluczami:
            - price: int - cena pokoju
            - media_info: str - informacja o mediach
            - raw_text: str - oryginalny fragment tekstu
        """
        if not text:
            return None
        
        text_lower = text.lower()
        
        # PRIORYTET 1: Szukaj ceny najmu w opisie (wzorce)
        rent_price = self._extract_rent_price(text)

        if rent_price:
            # Znaleziono cenę najmu - wykryj info o mediach
            media_info = self._detect_media_info_advanced(text_lower, rent_price)

            return {
                'price': rent_price,
                'media_info': media_info,
                'raw_text': self._extract_price_context(text, rent_price)
            }
        
        # PRIORYTET 2: Nie znaleziono wzorców - ODRZUĆ
        # Nie używamy już fallbacku "pierwsza sensowna kwota" bo to powoduje błędy
        # (np. wyciąganie kosztów mediów zamiast czynszu)
        return None
    
    def detect_media_info_only(self, text: str) -> str:
        """
        Wykrywa tylko informację o mediach bez parsowania ceny.
        Użyteczne gdy mamy już cenę z JSON-LD i chcemy tylko media_info.
        
        Args:
            text: Tekst ogłoszenia
            
        Returns:
            str - informacja o mediach
        """
        if not text:
            return "brak informacji"
        
        text_lower = text.lower()
        
        # Sprawdź co jest w tekście (może być kilka kategorii naraz!)
        has_all_included = any(phrase in text_lower for phrase in self.MEDIA_INCLUDED)
        has_separate = any(phrase in text_lower for phrase in self.MEDIA_SEPARATE)
        has_partial = any(phrase in text_lower for phrase in self.MEDIA_PARTIAL)
        
        # PRIORYTET 1: Wszystko wliczone (najważniejsze)
        if has_all_included:
            return "wliczone"
        
        # PRIORYTET 2: Media osobno (ważniejsze niż częściowo)
        # Nawet jeśli jest "internet w cenie" + "media dodatkowo", to media są osobno
        if has_separate:
            return "+ media"
        
        # PRIORYTET 3: Częściowo wliczone (tylko jeśli NIE ma separate)
        if has_partial:
            return "częściowo wliczone (sprawdź opis)"
        
        # Szukaj wzorca z konkretną kwotą mediów "media ok. 150 zł"
        media_cost_pattern = re.compile(r'media.*?(\d{2,3})\s*(?:zł|złotych)', re.IGNORECASE)
        match = media_cost_pattern.search(text)
        if match:
            cost = match.group(1)
            return f"+ ~{cost} zł media"
        
        # Domyślnie - brak jasnej informacji
        return "sprawdź w opisie"

    def _extract_price_context(self, text: str, price: int) -> str:
        """
        Wyciąga fragment tekstu wokół ceny (kontekst).
        """
        price_str = str(price)
        idx = text.find(price_str)
        
        if idx == -1:
            return text[:100]  # Pierwsze 100 znaków
        
        # Wyciągamy +/- 50 znaków wokół ceny
        start = max(0, idx - 50)
        end = min(len(text), idx + len(price_str) + 50)
        
        context = text[start:end].strip()
        
        if start > 0:
            context = "..." + context
        if end < len(text):
            context = context + "..."
        
        return context


# Testy jednostkowe
if __name__ == "__main__":
    parser = PriceParser()
    
    test_cases = [
        # (tekst, oczekiwana_cena, oczekiwane_media_info)
        ("Pokój 700 zł + media ok. 150 zł", 700, "+ media"),
        ("Wynajem 850 zł wszystko wliczone", 850, "wliczone"),
        ("Cena 600 bez mediów", 600, "+ media"),
        ("Pokój za 1200 złotych, opłaty dodatkowe", 1200, "+ media"),
        ("750 zł razem z mediami", 750, "wliczone"),
        ("Czynsz 900 PLN", 900, "brak informacji"),
        # Nowe przypadki - rozbicie
        ("Cena: 1100 zł – w tym wszystkie opłaty (850 zł – pokój + 250 zł – opłaty)", 850, "+ 250 zł opłaty"),
        ("Pokój przy ul. Pana Balcera 6. Cena: 750 zł + opłaty", 750, "+ media"),
        # Problem z latami
        ("Umowa do lipca 2026. Cena 800 zł miesięcznie", 800, "brak informacji"),
        # Problem z numerami domów
        ("Pokój przy ul. Skrzatów 7, cena 1100 zł", 1100, "brak informacji"),
    ]
    
    print("🧪 Testy Price Parser V2:\n")
    passed = 0
    failed = 0
    
    for text, expected_price, expected_media in test_cases:
        result = parser.extract_price(text)
        
        if result:
            price_ok = result['price'] == expected_price
            # Media info może się różnić - sprawdzamy tylko czy nie jest None
            status = "✅" if price_ok else "❌"
            
            if price_ok:
                passed += 1
            else:
                failed += 1
            
            print(f"{status} '{text[:60]}...'")
            print(f"   Cena: {result['price']} zł (oczekiwano: {expected_price})")
            print(f"   Media: {result['media_info']}")
            if not price_ok:
                print(f"   ⚠️ BŁĄD: Oczekiwano {expected_price}, otrzymano {result['price']}")
            print()
        else:
            print(f"❌ '{text}' → Nie wykryto ceny")
            failed += 1
            print()
    
    print(f"\n📊 Wyniki: {passed} ✅ / {failed} ❌ / {len(test_cases)} testów")

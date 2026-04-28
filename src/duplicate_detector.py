"""
Duplicate Detector - wykrywanie duplikatów ogłoszeń
Algorytm: Adres identyczny + opis podobny >95% = duplikat
"""

import Levenshtein
from typing import List, Dict

class DuplicateDetector:
    def __init__(self, similarity_threshold: float = 0.95):
        """
        Args:
            similarity_threshold: Próg podobieństwa (0-1), domyślnie 0.95 (95%)
        """
        self.threshold = similarity_threshold
    
    def calculate_similarity(self, text1: str, text2: str) -> float:
        """
        Oblicza podobieństwo dwóch tekstów używając Levenshtein distance.
        
        Returns:
            Float od 0 (całkowicie różne) do 1 (identyczne)
        """
        if not text1 or not text2:
            return 0.0
        
        # Normalizacja: małe litery, usunięcie nadmiarowych spacji
        text1 = ' '.join(text1.lower().split())
        text2 = ' '.join(text2.lower().split())
        
        # Obliczamy odległość Levenshteina
        distance = Levenshtein.distance(text1, text2)
        max_len = max(len(text1), len(text2))
        
        if max_len == 0:
            return 1.0
        
        # Podobieństwo = 1 - (distance / max_length)
        similarity = 1 - (distance / max_len)
        
        return similarity
    
    def is_duplicate(self, offer1: Dict, offer2: Dict) -> bool:
        """
        Sprawdza czy dwa ogłoszenia to duplikaty.
        
        Args:
            offer1, offer2: Dicts z kluczami: address, description
            
        Returns:
            True jeśli duplikat, False jeśli nie
        """
        # 1. Adres musi być identyczny
        addr1 = offer1.get('address', {}).get('full', '').lower().strip()
        addr2 = offer2.get('address', {}).get('full', '').lower().strip()
        
        if addr1 != addr2:
            return False
        
        # 2. Sprawdzamy podobieństwo opisów
        desc1 = offer1.get('description', '')
        desc2 = offer2.get('description', '')
        
        similarity = self.calculate_similarity(desc1, desc2)
        
        return similarity >= self.threshold
    
    def find_duplicates_in_batch(self, offers: List[Dict]) -> List[tuple]:
        """
        Znajduje wszystkie pary duplikatów w liście ogłoszeń.
        
        Args:
            offers: Lista ogłoszeń
            
        Returns:
            Lista tupli (index1, index2) wskazujących na duplikaty
        """
        duplicates = []
        
        for i in range(len(offers)):
            for j in range(i + 1, len(offers)):
                if self.is_duplicate(offers[i], offers[j]):
                    duplicates.append((i, j))
        
        return duplicates
    
    def filter_duplicates(self, new_offer: Dict, existing_offers: List[Dict]) -> bool:
        """
        Sprawdza czy nowe ogłoszenie jest duplikatem któregoś z istniejących.
        
        Args:
            new_offer: Nowe ogłoszenie do sprawdzenia
            existing_offers: Lista istniejących ogłoszeń
            
        Returns:
            True jeśli to duplikat (ODRZUĆ), False jeśli unikalne (AKCEPTUJ)
        """
        for existing in existing_offers:
            if self.is_duplicate(new_offer, existing):
                return True  # Znaleziono duplikat
        
        return False  # Unikalne ogłoszenie


# Testy jednostkowe
if __name__ == "__main__":
    detector = DuplicateDetector(similarity_threshold=0.95)
    
    # Test 1: Podobieństwo tekstów
    print("🧪 Test 1 - Podobieństwo tekstów:\n")
    
    text_pairs = [
        ("Pokój przy Narutowicza 5, 700 zł, umeblowany", 
         "Pokój przy Narutowicza 5, 700 zł, umeblowany", 
         1.0),  # Identyczne
        
        ("Pokój przy Narutowicza 5, 700 zł, umeblowany", 
         "Przytulny pokój Narutowicza 5, meble, 700zł", 
         0.6),  # Podobne ale <95%
        
        ("Pokój przy Narutowicza 5, 700 zł, umeblowany", 
         "Pokój przy Narutowicza 5, 700 zł, umeblowany!!!", 
         0.97),  # >95%
    ]
    
    for text1, text2, expected in text_pairs:
        similarity = detector.calculate_similarity(text1, text2)
        print(f"Podobieństwo: {similarity:.2%} (oczekiwano ~{expected:.2%})")
        print(f"  Text 1: {text1}")
        print(f"  Text 2: {text2}\n")
    
    # Test 2: Wykrywanie duplikatów
    print("\n🧪 Test 2 - Wykrywanie duplikatów:\n")
    
    offer1 = {
        'address': {'full': 'Narutowicza 5'},
        'description': 'Pokój przy Narutowicza 5, 700 zł, umeblowany'
    }
    
    offer2 = {
        'address': {'full': 'Narutowicza 5'},
        'description': 'Pokój przy Narutowicza 5, 700 zł, umeblowany!!!'  # >95% podobny
    }
    
    offer3 = {
        'address': {'full': 'Racławickie 10'},
        'description': 'Pokój przy Narutowicza 5, 700 zł, umeblowany'  # Inny adres
    }
    
    is_dup_12 = detector.is_duplicate(offer1, offer2)
    is_dup_13 = detector.is_duplicate(offer1, offer3)
    
    print(f"Offer1 vs Offer2 (ten sam adres, 93.62% podobny opis): {is_dup_12} (oczekiwano: False, bo <95%)")
    print(f"Offer1 vs Offer3 (inny adres): {is_dup_13} (oczekiwano: False)")

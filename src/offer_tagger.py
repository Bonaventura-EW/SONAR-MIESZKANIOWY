#!/usr/bin/env python3
"""
SONAR MIESZKANIOWY - Moduł tagowania ofert (B1)
Automatycznie klasyfikuje oferty jako: kawalerka / pokój / mieszkanie
Jedna oferta może mieć wiele tagów, z priorytetem (główny + dodatkowe)
"""

import re
from typing import Dict, List, Tuple

# Definicje tagów
TAGS = {
    'pokoj': {
        'label': 'Pokój',
        'color': '#3b82f6',  # niebieski
        'icon': '🛏️',
        'priority': 1
    },
    'kawalerka': {
        'label': 'Kawalerka',
        'color': '#10b981',  # zielony
        'icon': '🏠',
        'priority': 2
    },
    'mieszkanie': {
        'label': 'Mieszkanie',
        'color': '#8b5cf6',  # fioletowy
        'icon': '🏢',
        'priority': 3
    }
}

# Wzorce regex dla każdego typu
PATTERNS = {
    'pokoj': [
        # Bezpośrednie wzorce
        r'\bpok[oó]j\b',
        r'\bpokoje\b',
        r'\bpokoi\b',
        r'\bpokoju\b',
        r'\bpokojem\b',
        r'\bmieszkaniowy\b',
        r'\bpokojow[aey]\b',
        # Specyficzne frazy
        r'\bpok[oó]j\s+(jedno|dwu|trzy)osobowy\b',
        r'\b(jedno|dwu|trzy)osobowy\s+pok[oó]j\b',
        r'\bpok[oó]j\s+dla\s+(student|kobiet|m[eę][żz]czyzn|par|osob)',
        r'\bpok[oó]j\s+do\s+wynaj[eę]cia\b',
        r'\bwynajm[eę]\s+pok[oó]j\b',
        r'\bwolny\s+pok[oó]j\b',
        # Pokój w mieszkaniu
        r'\bpok[oó]j\s+w\s+mieszkaniu\b',
        r'\bpok[oó]j\s+w\s+domu\b',
        # Liczba pokoi jako wskaźnik że to mieszkanie z pokojami
        r'\b[2-5]\s*-?\s*pokojow[ey]\b',
        r'\bmieszkanie\s+[2-5]\s*-?\s*pokojow[ey]\b',
    ],
    'kawalerka': [
        # Bezpośrednie wzorce
        r'\bkawalerk[aąeęioy]\b',
        r'\bkawalerka\b',
        r'\bkawalerki\b',
        r'\bkawalerce\b',
        r'\bkawalerk[ąę]\b',
        # Studio
        r'\bstudio\b',
        r'\bapartament\s+studio\b',
        # Małe mieszkanie jednopokojowe
        r'\b(1|jedno)\s*-?\s*pokojow[ey]\b',
        r'\bmieszkanie\s+jednopokojow[ey]\b',
        # Garsoniera
        r'\bgarsonier[aąey]\b',
    ],
    'mieszkanie': [
        # Bezpośrednie wzorce
        r'\bmieszkani[eauoy]\b',
        r'\bmieszkaniem\b',
        r'\bmieszkań\b',
        # Całe mieszkanie
        r'\bca[lł][eoy]\s+mieszkani[eauoy]\b',
        r'\bwynajm[eę]\s+mieszkani[eauoy]\b',
        r'\bmieszkani[eauoy]\s+do\s+wynaj[eę]cia\b',
        # Apartament
        r'\bapartament[uyo]?\b',
        r'\bapartamenty\b',
        # Lokalizacje mieszkalne
        r'\bblok[uia]?\b',
        r'\bklatk[aąey]\s+schodow[aąey]\b',
        # Wielopokojowe
        r'\b[2-5]\s*-?\s*pokojow[ey]\s+mieszkani[eauoy]\b',
    ]
}

# Wzorce wykluczające (jeśli pasują, zmniejsz pewność)
NEGATIVE_PATTERNS = {
    'pokoj': [
        r'\bpokoje\s+go[sś]cinne\s+w\s+hotelu\b',  # hotel
        r'\bpok[oó]j\s+hotelowy\b',
    ],
    'kawalerka': [],
    'mieszkanie': [
        r'\bbiuro\b',
        r'\blokal\s+u[żz]ytkowy\b',
    ]
}

# Frazy które jednoznacznie wskazują typ
DEFINITIVE_PHRASES = {
    'pokoj': [
        r'\bpok[oó]j\s+do\s+wynaj[eę]cia\b',
        r'\bwynajm[eę]\s+pok[oó]j\b',
        r'\bpok[oó]j\s+dla\s+student',
        r'\bpok[oó]j\s+(jedno|dwu)osobowy\b',
        r'\bwolny\s+pok[oó]j\s+w\s+mieszkaniu\b',
    ],
    'kawalerka': [
        r'\bkawalerk[aąeęioy]\s+do\s+wynaj[eę]cia\b',
        r'\bwynajm[eę]\s+kawalerk[aąeęioy]\b',
        r'\bstudio\s+do\s+wynaj[eę]cia\b',
    ],
    'mieszkanie': [
        r'\bca[lł][eoy]\s+mieszkani[eauoy]\s+do\s+wynaj[eę]cia\b',
        r'\bwynajm[eę]\s+ca[lł][eoy]\s+mieszkani[eauoy]\b',
        r'\bmieszkani[eauoy]\s+[2-5]\s*-?\s*pokojow[ey]\b',
    ]
}


def analyze_text(text: str) -> Dict[str, float]:
    """
    Analizuje tekst i zwraca wyniki dla każdego tagu.
    Returns: {'pokoj': 0.85, 'kawalerka': 0.1, 'mieszkanie': 0.6}
    """
    if not text:
        return {'pokoj': 0.0, 'kawalerka': 0.0, 'mieszkanie': 0.0}
    
    text_lower = text.lower()
    scores = {'pokoj': 0.0, 'kawalerka': 0.0, 'mieszkanie': 0.0}
    
    for tag_type in ['pokoj', 'kawalerka', 'mieszkanie']:
        # Sprawdź frazy definitywne (wysokie wyniki)
        for pattern in DEFINITIVE_PHRASES.get(tag_type, []):
            if re.search(pattern, text_lower):
                scores[tag_type] += 0.5
        
        # Sprawdź standardowe wzorce
        for pattern in PATTERNS.get(tag_type, []):
            matches = re.findall(pattern, text_lower)
            scores[tag_type] += len(matches) * 0.15
        
        # Sprawdź wzorce wykluczające
        for pattern in NEGATIVE_PATTERNS.get(tag_type, []):
            if re.search(pattern, text_lower):
                scores[tag_type] -= 0.3
        
        # Normalizuj do 0-1
        scores[tag_type] = max(0.0, min(1.0, scores[tag_type]))
    
    return scores


def determine_tags(scores: Dict[str, float], threshold: float = 0.15) -> Dict:
    """
    Określa tagi na podstawie wyników analizy.
    Zwraca tag główny (najwyższy wynik) + tagi dodatkowe.
    
    Returns: {
        'primary': 'pokoj',
        'secondary': ['mieszkanie'],
        'all_tags': ['pokoj', 'mieszkanie'],
        'scores': {'pokoj': 0.85, ...}
    }
    """
    # Filtruj tagi powyżej progu
    valid_tags = [(tag, score) for tag, score in scores.items() if score >= threshold]
    
    if not valid_tags:
        # Domyślnie zakładamy mieszkanie dla OLX mieszkania
        return {
            'primary': 'mieszkanie',
            'secondary': [],
            'all_tags': ['mieszkanie'],
            'scores': scores
        }
    
    # Sortuj po wyniku (malejąco)
    valid_tags.sort(key=lambda x: x[1], reverse=True)
    
    primary = valid_tags[0][0]
    secondary = [tag for tag, _ in valid_tags[1:]]
    
    return {
        'primary': primary,
        'secondary': secondary,
        'all_tags': [primary] + secondary,
        'scores': scores
    }


def tag_offer(title: str, description: str) -> Dict:
    """
    Główna funkcja - taguje ofertę na podstawie tytułu i opisu.
    Tytuł ma większą wagę niż opis.
    
    Args:
        title: Tytuł oferty
        description: Opis oferty
    
    Returns: {
        'primary': 'pokoj',
        'secondary': ['mieszkanie'],
        'all_tags': ['pokoj', 'mieszkanie'],
        'scores': {...},
        'confidence': 0.85
    }
    """
    # Analizuj tytuł (waga 2x)
    title_scores = analyze_text(title)
    
    # Analizuj opis (waga 1x)
    desc_scores = analyze_text(description)
    
    # Połącz wyniki z wagami
    combined_scores = {}
    for tag in ['pokoj', 'kawalerka', 'mieszkanie']:
        combined_scores[tag] = (title_scores[tag] * 2 + desc_scores[tag]) / 3
    
    # Określ tagi
    result = determine_tags(combined_scores)
    
    # Oblicz pewność (confidence)
    primary_score = result['scores'][result['primary']]
    
    # Jeśli wynik jest niski, zmniejsz confidence
    if primary_score < 0.2:
        confidence = 0.3
    elif primary_score < 0.4:
        confidence = 0.6
    else:
        confidence = min(0.95, primary_score + 0.3)
    
    result['confidence'] = round(confidence, 2)
    
    return result


def get_tag_info(tag_type: str) -> Dict:
    """Zwraca informacje o tagu (kolor, ikona, etykieta)."""
    return TAGS.get(tag_type, TAGS['pokoj'])


def build_tags(title: str, description: str) -> Dict:
    """Zwraca tagi w kształcie używanym przez frontend/data.json.

    Jedno źródło prawdy dla struktury {primary, secondary, all, confidence}.
    Liczone raz w main.py przy przetwarzaniu oferty i zapisywane w offers.json;
    map_generator tylko je odczytuje (z fallbackiem na żywo dla starych ofert).
    """
    r = tag_offer(title, description)
    return {
        'primary': r['primary'],
        'secondary': r['secondary'],
        'all': r['all_tags'],
        'confidence': r['confidence'],
    }


def title_from_url(url: str) -> str:
    """Wyciąga „tytuł" ze slugu URL (część przed CID), do tagowania."""
    if not url:
        return ''
    return url.split('/')[-1].split('.')[0].replace('-', ' ')


def format_tags_for_display(tag_result: Dict) -> str:
    """Formatuje tagi do wyświetlenia (np. w popupie)."""
    primary = tag_result['primary']
    primary_info = get_tag_info(primary)
    
    parts = [f"{primary_info['icon']} {primary_info['label']}"]
    
    for secondary in tag_result.get('secondary', []):
        sec_info = get_tag_info(secondary)
        parts.append(f"+ {sec_info['label']}")
    
    return ' '.join(parts)


# ============ TESTY ============
if __name__ == '__main__':
    test_cases = [
        ("Pokój do wynajęcia Lublin", "Wynajmę pokój jednoosobowy w mieszkaniu 3-mieszkaniowym."),
        ("Kawalerka Śródmieście", "Studio 25m2, kuchnia aneks, łazienka."),
        ("Mieszkanie 2-pokojowe", "Do wynajęcia całe mieszkanie z dwoma pokojami."),
        ("Pokój dla studentki", "Wolny pokój w mieszkaniu studenckim, blisko UMCS."),
        ("", "Pokój w mieszkaniu 2-mieszkaniowym, dla kobiety."),
    ]
    
    print("=" * 60)
    print("TESTY TAGOWANIA OFERT")
    print("=" * 60)
    
    for title, desc in test_cases:
        result = tag_offer(title, desc)
        print(f"\nTytuł: {title}")
        print(f"Opis: {desc[:50]}...")
        print(f"→ Główny: {result['primary']} ({result['scores'][result['primary']]:.2f})")
        print(f"→ Dodatkowe: {result['secondary']}")
        print(f"→ Pewność: {result['confidence']}")
        print(f"→ Wyświetlenie: {format_tags_for_display(result)}")

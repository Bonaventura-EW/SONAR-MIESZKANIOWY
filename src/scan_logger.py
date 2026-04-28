"""
Scan Logger - zapisuje statystyki każdego skanu do pliku JSON
Używane przez monitoring dashboard
"""

import json
from pathlib import Path
from datetime import datetime
from typing import Dict, List
import pytz


class ScanLogger:
    def __init__(self, log_file: str = "../data/scan_history.json"):
        self.log_file = Path(log_file)
        self.tz = pytz.timezone('Europe/Warsaw')
        self.current_scan = None
        
    def start_scan(self) -> Dict:
        """
        Rozpoczyna nowy scan i zwraca obiekt z metadanymi.
        """
        self.current_scan = {
            'timestamp': datetime.now(self.tz).isoformat(),
            'status': 'running',
            'phases': {},
            'stats': {},
            'errors': []
        }
        return self.current_scan
    
    def log_phase(self, phase_name: str, duration: float, details: Dict = None):
        """
        Loguje czas wykonania fazy.
        
        Args:
            phase_name: Nazwa fazy (np. 'scraping', 'processing', 'geocoding')
            duration: Czas wykonania w sekundach
            details: Dodatkowe szczegóły
        """
        if not self.current_scan:
            return
        
        self.current_scan['phases'][phase_name] = {
            'duration': round(duration, 2),
            'details': details or {}
        }
    
    def log_stats(self, stats: Dict):
        """
        Zapisuje statystyki skanu.
        
        Args:
            stats: Dict ze statystykami (raw_offers, processed, new, updated, etc.)
        """
        if not self.current_scan:
            return
        
        self.current_scan['stats'] = stats
    
    def log_error(self, error: str):
        """Dodaje błąd do logu."""
        if not self.current_scan:
            return
        
        self.current_scan['errors'].append({
            'timestamp': datetime.now(self.tz).isoformat(),
            'message': error
        })
    
    def end_scan(self, status: str = 'completed', total_duration: float = None):
        """
        Kończy scan i zapisuje do pliku.
        
        Args:
            status: Status końcowy ('completed', 'failed', 'partial')
            total_duration: Całkowity czas wykonania w sekundach
        """
        if not self.current_scan:
            return
        
        self.current_scan['status'] = status
        self.current_scan['end_timestamp'] = datetime.now(self.tz).isoformat()
        
        if total_duration:
            self.current_scan['total_duration'] = round(total_duration, 2)
        
        # Oblicz metryki wydajności
        performance_metrics = self._calculate_performance_metrics()
        if performance_metrics:
            self.current_scan['performance'] = performance_metrics
        
        # Wczytaj istniejącą historię
        history = self._load_history()
        
        # Dodaj obecny scan
        history.append(self.current_scan)
        
        # Zachowaj tylko ostatnie 100 skanów
        history = history[-100:]
        
        # Zapisz
        self._save_history(history)
        
        # Reset
        self.current_scan = None
    
    def _calculate_performance_metrics(self) -> Dict:
        """
        Oblicza metryki wydajności na podstawie zebranych danych.
        
        Returns:
            Dict z metrykami: offers_per_second, pages_scanned, geocoding_duration
        """
        if not self.current_scan:
            return {}
        
        metrics = {}
        phases = self.current_scan.get('phases', {})
        stats = self.current_scan.get('stats', {})
        
        # 1. Oferty na sekundę (total)
        total_duration = self.current_scan.get('total_duration', 0)
        raw_offers = stats.get('raw_offers', 0)
        
        if total_duration > 0 and raw_offers > 0:
            metrics['offers_per_second'] = round(raw_offers / total_duration, 2)
        
        # 2. Strony przeskanowane
        scraping_phase = phases.get('scraping', {})
        max_pages = scraping_phase.get('details', {}).get('max_pages', 0)
        if max_pages > 0:
            metrics['pages_scanned'] = max_pages
        
        # 3. Czas geokodowania
        geocoding_phase = phases.get('geocoding', {})
        if geocoding_phase:
            metrics['geocoding_duration'] = geocoding_phase.get('duration', 0)
            geocoded = geocoding_phase.get('details', {}).get('geocoded_addresses', 0)
            if geocoded > 0 and metrics['geocoding_duration'] > 0:
                metrics['geocoding_per_address'] = round(metrics['geocoding_duration'] / geocoded, 2)
        
        # 4. Czas scrapingu na stronę
        scraping_duration = scraping_phase.get('duration', 0)
        if scraping_duration > 0 and max_pages > 0:
            metrics['scraping_per_page'] = round(scraping_duration / max_pages, 2)
        
        # 5. Współczynnik przetworzonych ofert (processed / raw)
        processed = stats.get('processed', 0)
        if raw_offers > 0:
            metrics['processing_success_rate'] = round((processed / raw_offers) * 100, 1)
        
        return metrics
    
    def _load_history(self) -> List[Dict]:
        """Wczytuje historię skanów z pliku."""
        if self.log_file.exists():
            try:
                with open(self.log_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except json.JSONDecodeError:
                print("⚠️ Uszkodzony plik historii skanów, tworzę nowy")
                return []
        return []
    
    def _save_history(self, history: List[Dict]):
        """Zapisuje historię skanów do pliku."""
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.log_file, 'w', encoding='utf-8') as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
    
    def get_recent_scans(self, count: int = 10) -> List[Dict]:
        """
        Zwraca ostatnie N skanów.
        
        Args:
            count: Liczba skanów do zwrócenia
            
        Returns:
            Lista ostatnich skanów (od najnowszego)
        """
        history = self._load_history()
        return history[-count:][::-1]  # Odwróć kolejność (najnowsze pierwsze)
    
    def get_statistics(self) -> Dict:
        """
        Oblicza statystyki ze wszystkich skanów.
        
        Returns:
            Dict z agregatami (średni czas, success rate, etc.)
        """
        history = self._load_history()
        
        if not history:
            return {
                'total_scans': 0,
                'successful': 0,
                'failed': 0,
                'avg_duration': 0,
                'avg_offers_found': 0
            }
        
        total = len(history)
        successful = sum(1 for s in history if s['status'] == 'completed')
        failed = total - successful
        
        # Średni czas (tylko dla zakończonych)
        durations = [s.get('total_duration', 0) for s in history if 'total_duration' in s]
        avg_duration = sum(durations) / len(durations) if durations else 0
        
        # Średnia liczba ofert
        offers_counts = [s['stats'].get('raw_offers', 0) for s in history if 'stats' in s]
        avg_offers = sum(offers_counts) / len(offers_counts) if offers_counts else 0
        
        return {
            'total_scans': total,
            'successful': successful,
            'failed': failed,
            'success_rate': (successful / total * 100) if total > 0 else 0,
            'avg_duration': round(avg_duration, 2),
            'avg_offers_found': round(avg_offers, 1)
        }


# Test
if __name__ == "__main__":
    logger = ScanLogger(log_file="../data/scan_history.json")
    
    # Symulacja skanu
    import time
    
    logger.start_scan()
    
    # Faza 1: Scraping
    time.sleep(0.5)
    logger.log_phase('scraping', 12.5, {'pages': 5, 'offers': 120})
    
    # Faza 2: Processing
    time.sleep(0.3)
    logger.log_phase('processing', 8.2, {'valid': 95, 'rejected': 25})
    
    # Statystyki
    logger.log_stats({
        'raw_offers': 120,
        'processed': 95,
        'new': 10,
        'updated': 85,
        'duplicates': 5
    })
    
    # Zakończ
    logger.end_scan('completed', total_duration=20.7)
    
    print("✅ Test zakończony - sprawdź data/scan_history.json")
    print(f"\nStatystyki: {logger.get_statistics()}")

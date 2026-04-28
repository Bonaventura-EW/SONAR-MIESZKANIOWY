"""
Monitoring Data Generator - przygotowuje dane dla dashboardu monitoringu
"""

import json
from pathlib import Path
from scan_logger import ScanLogger


def generate_monitoring_data():
    """
    Generuje plik monitoring_data.json z pełnymi statystykami dla dashboardu.
    """
    logger = ScanLogger(log_file="../data/scan_history.json")
    
    # Pobierz ostatnie 100 skanów (dla wykresów ~33 dni) i statystyki
    recent_scans = logger.get_recent_scans(count=100)
    statistics = logger.get_statistics()
    
    # Przygotuj dane dla wykresów
    chart_data = {
        'duration_over_time': [],
        'offers_over_time': [],
        'success_rate': []
    }
    
    for scan in reversed(recent_scans):  # Odwróć na chronologiczną kolejność
        timestamp = scan.get('timestamp', '')
        performance = scan.get('performance', {})
        
        # Wykres czasu wykonania + metryki wydajności
        if 'total_duration' in scan:
            chart_data['duration_over_time'].append({
                'timestamp': timestamp,
                'duration': scan['total_duration'],
                'offers_per_second': performance.get('offers_per_second', 0),
                'scraping_per_page': performance.get('scraping_per_page', 0),
                'geocoding_duration': performance.get('geocoding_duration', 0),
                'geocoding_per_address': performance.get('geocoding_per_address', 0)
            })
        
        # Wykres liczby ofert
        if 'stats' in scan:
            chart_data['offers_over_time'].append({
                'timestamp': timestamp,
                'raw_offers': scan['stats'].get('raw_offers', 0),
                'processed': scan['stats'].get('processed', 0),
                'new': scan['stats'].get('new', 0)
            })
        
        # Wykres success rate
        status = scan.get('status', 'unknown')
        success_value = 100 if status == 'completed' else 0
        chart_data['success_rate'].append({
            'timestamp': timestamp,
            'success': success_value,
            'status': status
        })
    
    # Posortuj wszystkie wykresy chronologicznie po timestamp
    for key in chart_data:
        chart_data[key] = sorted(chart_data[key], key=lambda x: x['timestamp'])
    
    # Zbierz dane dla podstrony
    monitoring_data = {
        'generated_at': recent_scans[0]['timestamp'] if recent_scans else None,
        'statistics': statistics,
        'recent_scans': recent_scans[:84],  # Ostatnie 28 dni (3 skany/dzień)
        'charts': chart_data
    }
    
    # Zapisz do docs/
    output_file = Path("../docs/monitoring_data.json")
    output_file.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(monitoring_data, f, ensure_ascii=False, indent=2)
    
    print(f"✅ Dane monitoringu wygenerowane: {output_file}")
    print(f"   Statystyki: {statistics}")
    print(f"   Ostatnich skanów: {len(recent_scans)}")


if __name__ == "__main__":
    generate_monitoring_data()

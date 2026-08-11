"""
Monitoring Data Generator - przygotowuje dane dla dashboardu monitoringu
"""

import json
from pathlib import Path
from scan_logger import ScanLogger
import paths


def generate_monitoring_data():
    """
    Generuje plik monitoring_data.json z pełnymi statystykami dla dashboardu.
    """
    logger = ScanLogger(log_file=paths.SCAN_HISTORY_JSON)
    
    # Pobierz ostatnie 100 skanów (dla wykresów ~33 dni) i statystyki
    recent_scans = logger.get_recent_scans(count=100)
    statistics = logger.get_statistics()
    
    # Przygotuj dane dla wykresów
    chart_data = {
        'duration_over_time': [],
        'offers_over_time': [],
        'success_rate': [],
        # FIX 2026-08-09: jakość mapy w czasie — udział pinezek dokładnych oraz
        # ofert, które w ogóle nie trafiły na mapę. Regresja parsera adresów albo
        # geokodera widać tu od razu, bez ręcznego liczenia po każdym skanie.
        'map_quality': [],
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
                'new': scan['stats'].get('new', 0),
                'disappeared': scan['stats'].get('disappeared'),  # None gdy stary skan
                'confirmed_inactive': (scan['stats'].get('verification') or {}).get('confirmed_inactive')
            })
        
        # Wykres jakości mapy — tylko skany, które tę metrykę zapisały
        # (starsze wpisy w historii jej nie mają i celowo ich nie zmyślamy).
        quality = (scan.get('stats') or {}).get('map_quality')
        if quality:
            active = quality.get('active') or 0
            precision = quality.get('precision') or {}
            chart_data['map_quality'].append({
                'timestamp': timestamp,
                'active': active,
                'on_map': quality.get('on_map', 0),
                'off_map': quality.get('off_map', 0),
                'exact': precision.get('exact', 0),
                'street': precision.get('street', 0),
                'none': precision.get('none', 0),
                'exact_pct': round(precision.get('exact', 0) / active * 100, 1) if active else 0,
                'off_map_pct': round(quality.get('off_map', 0) / active * 100, 1) if active else 0,
            })

        # Wykres success rate
        # FIX 2026-08-11: „completed" z błędem (blokada OLX) to nie sukces —
        # inaczej wykres świecił 100% podczas serii zablokowanych skanów.
        status = scan.get('status', 'unknown')
        has_errors = bool(scan.get('errors'))
        success_value = 100 if (status == 'completed' and not has_errors) else 0
        chart_data['success_rate'].append({
            'timestamp': timestamp,
            'success': success_value,
            'status': status,
            'hasErrors': has_errors,
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
    output_file = Path(paths.DOCS_MONITORING_JSON)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(monitoring_data, f, ensure_ascii=False, indent=2)
    
    print(f"✅ Dane monitoringu wygenerowane: {output_file}")
    print(f"   Statystyki: {statistics}")
    print(f"   Ostatnich skanów: {len(recent_scans)}")


if __name__ == "__main__":
    generate_monitoring_data()

"""
API Generator - generuje statyczne pliki JSON dla aplikacji mobilnej

Endpointy (pliki statyczne na GitHub Pages):
- /api/status.json    - aktualny status + ostatni skan
- /api/history.json   - historia ostatnich 20 skanów
- /api/health.json    - prosty health check

Architektura przygotowana na dodanie SZPERACZ w przyszłości.
"""

import json
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import pytz

from scan_logger import ScanLogger
import paths


class APIGenerator:
    """Generator statycznych plików JSON API dla aplikacji mobilnej."""
    
    # Harmonogram skanów (CET/CEST) — musi odpowiadać cronowi w scanner.yml
    # FIX 2026-06-12: cron działa o :17 (off-peak), nie o pełnych godzinach
    SCAN_SCHEDULE = ["09:17", "15:17", "21:17"]
    
    def __init__(self, output_dir: str = paths.DOCS_API_DIR):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.tz = pytz.timezone('Europe/Warsaw')
        self.logger = ScanLogger(log_file=paths.SCAN_HISTORY_JSON)
    
    def generate_all(self):
        """Generuje wszystkie pliki API."""
        print("🔄 Generowanie API dla aplikacji mobilnej...")
        
        self._generate_status()
        self._generate_history()
        self._generate_health()
        
        print(f"✅ API wygenerowane w: {self.output_dir}")
    
    def _generate_status(self):
        """
        Generuje /api/status.json
        
        Zawiera:
        - Aktualny status systemu
        - Szczegóły ostatniego skanu
        - Przewidywany czas następnego skanu
        - Flagi dla powiadomień (hasErrors, isHealthy)
        """
        recent_scans = self.logger.get_recent_scans(count=6)
        statistics = self.logger.get_statistics()
        
        last_scan = recent_scans[0] if recent_scans else None
        
        # Oblicz następny zaplanowany skan
        next_scan_time = self._calculate_next_scan_time()
        
        # Sprawdź czy ostatni skan miał błędy
        has_errors = False
        error_messages = []
        if last_scan:
            errors = last_scan.get('errors', [])
            if errors:
                has_errors = True
                error_messages = [e.get('message', 'Unknown error') for e in errors]
        
        # Określ status systemu
        system_status = self._determine_system_status(last_scan, statistics)
        
        # Sformatowany ostatni skan — używamy w dwóch miejscach
        formatted_last_scan = self._format_scan_for_api(last_scan) if last_scan else None
        
        status_data = {
            "system": "sonar",
            "version": "1.0.0",
            "generatedAt": datetime.now(self.tz).isoformat(),
            
            "status": {
                "current": system_status,
                "isHealthy": system_status in ["operational", "degraded"],
                "hasErrors": has_errors,
                "errorMessages": error_messages
            },
            
            # Gotowe teksty powiadomienia push na poziomie głównym —
            # aplikacja Android czyta notification.title i notification.body wprost,
            # bez zagłębiania się w lastScan.
            "notification": formatted_last_scan["notification"] if formatted_last_scan else None,
            
            "lastScan": formatted_last_scan,
            
            # 6 ostatnich skanów w skróconym formacie — do paska historii w UI
            # Każdy wpis: id, scanTimeFormatted, uiStatus, offers.new, hasErrors
            "recentScans": [
                self._format_scan_short(s) for s in recent_scans
            ],
            
            "schedule": {
                "times": self.SCAN_SCHEDULE,
                "timezone": "Europe/Warsaw",
                "nextScanAt": next_scan_time.isoformat() if next_scan_time else None
            },
            
            "statistics": {
                "totalScans": statistics.get('total_scans', 0),
                "successRate": round(statistics.get('success_rate', 0), 1),
                "avgDurationSeconds": statistics.get('avg_duration', 0),
                "avgOffersFound": statistics.get('avg_offers_found', 0)
            }
        }
        
        self._save_json("status.json", status_data)
        print(f"   📊 status.json - status: {system_status}")
    
    def _generate_history(self):
        """
        Generuje /api/history.json
        
        Zawiera ostatnie 20 skanów z pełnymi szczegółami.
        Używane do wyświetlania historii w aplikacji.
        """
        recent_scans = self.logger.get_recent_scans(count=20)
        
        history_data = {
            "system": "sonar",
            "generatedAt": datetime.now(self.tz).isoformat(),
            "count": len(recent_scans),
            "scans": [self._format_scan_for_api(scan) for scan in recent_scans]
        }
        
        self._save_json("history.json", history_data)
        print(f"   📜 history.json - {len(recent_scans)} skanów")
    
    def _generate_health(self):
        """
        Generuje /api/health.json
        
        Prosty health check - aplikacja może odpytywać ten endpoint
        żeby sprawdzić czy API jest dostępne i aktualne.
        """
        recent_scans = self.logger.get_recent_scans(count=1)
        last_scan = recent_scans[0] if recent_scans else None
        
        # Sprawdź czy ostatni skan był w ciągu ostatnich 12h
        is_fresh = False
        hours_since_last_scan = None
        
        if last_scan:
            try:
                last_scan_time = datetime.fromisoformat(last_scan['timestamp'])
                now = datetime.now(self.tz)
                delta = now - last_scan_time
                hours_since_last_scan = round(delta.total_seconds() / 3600, 1)
                is_fresh = hours_since_last_scan < 12
            except (KeyError, ValueError):
                pass
        
        health_data = {
            "status": "ok" if is_fresh else "stale",
            "timestamp": datetime.now(self.tz).isoformat(),
            "lastScanAt": last_scan['timestamp'] if last_scan else None,
            "hoursSinceLastScan": hours_since_last_scan,
            "isFresh": is_fresh,
            "systems": {
                "sonar": {
                    "enabled": True,
                    "lastStatus": last_scan.get('status', 'unknown') if last_scan else 'unknown'
                },
                "szperacz": {
                    "enabled": False,
                    "lastStatus": None,
                    "message": "Coming soon"
                }
            }
        }
        
        self._save_json("health.json", health_data)
        print(f"   💓 health.json - {'fresh' if is_fresh else 'stale'} ({hours_since_last_scan}h ago)")
    
    def _format_scan_for_api(self, scan: Dict) -> Dict:
        """
        Formatuje pojedynczy skan do formatu API.
        Upraszcza strukturę i dodaje pola przydatne dla aplikacji mobilnej.
        """
        if not scan:
            return None
        
        stats = scan.get('stats', {})
        errors = scan.get('errors', [])
        
        # Określ status dla UI
        ui_status = "success"
        if scan.get('status') != 'completed':
            ui_status = "failed"
        elif errors:
            ui_status = "warning"
        
        new_count = stats.get('new', 0)
        # None = pole nie istnieje (stary skan przed wdrożeniem), 0 = naprawdę nic nie znikło
        disappeared_count = self._disappeared_count(stats)
        
        # Czytelny czas skanu (np. "15:51")
        scan_time_formatted = self._format_scan_time(scan.get('timestamp'))
        
        # Czytelny powód niepowodzenia (dla UI przy failed/warning)
        failure_reason = self._build_failure_reason(ui_status, errors, stats)
        
        # Gotowe teksty powiadomienia push — aplikacja wyświetla wprost
        notification = self._build_notification(
            ui_status=ui_status,
            scan_time=scan_time_formatted,
            new_count=new_count,
            disappeared_count=disappeared_count,
            errors=errors,
        )
        
        return {
            "id": scan.get('timestamp', '')[:19].replace(':', '-'),  # Unikalne ID
            "timestamp": scan.get('timestamp'),
            "endTimestamp": scan.get('end_timestamp'),
            "durationSeconds": scan.get('total_duration'),
            "durationFormatted": self._format_duration(scan.get('total_duration')),
            
            "uiStatus": ui_status,          # success | warning | failed
            "rawStatus": scan.get('status'),
            "scanTimeFormatted": scan_time_formatted,  # "15:51"
            "failureReason": failure_reason,            # None lub czytelny string
            
            # Gotowe teksty do powiadomienia push
            "notification": notification,
            
            "offers": {
                "found": stats.get('raw_offers', 0),
                "processed": stats.get('processed', 0),
                "new": new_count,
                "disappeared": self._disappeared_count(stats),  # spójne z kolumną „Znikło" w monitoringu
                "updated": stats.get('updated', 0),
                "active": stats.get('active', 0),
                "inactive": stats.get('inactive', 0)
            },
            
            "skipped": {
                "noAddress": stats.get('skipped_no_address', 0),
                "noCoords": stats.get('skipped_no_coords', 0),
                "duplicates": stats.get('skipped_duplicate', 0)
            },
            
            "errors": [
                {
                    "message": e.get('message', 'Unknown error'),
                    "timestamp": e.get('timestamp')
                }
                for e in errors
            ],
            "hasErrors": len(errors) > 0
        }
    
    def _format_scan_time(self, timestamp: Optional[str]) -> Optional[str]:
        """
        Zwraca godzinę skanu w formacie HH:MM (np. "15:51").
        Aplikacja wyświetla to wprost w powiadomieniu.
        """
        if not timestamp:
            return None
        try:
            dt = datetime.fromisoformat(timestamp)
            return dt.strftime('%H:%M')
        except (ValueError, TypeError):
            return None
    
    def _build_failure_reason(
        self,
        ui_status: str,
        errors: list,
        stats: Dict,
    ) -> Optional[str]:
        """
        Buduje czytelny opis przyczyny niepowodzenia / ostrzeżenia.
        Zwraca None gdy skan był sukcesem.
        
        Priorytet: błędy techniczne > brak ofert > niski wynik przetwarzania.
        """
        if ui_status == "success":
            return None
        
        # 1. Błędy techniczne z listy errors (np. wyjątki, timeout)
        if errors:
            messages = [e.get('message', '') for e in errors if e.get('message')]
            if messages:
                return '; '.join(messages[:3])  # Maks. 3 pierwsze
        
        # 2. Skan ukończony, ale status != completed (np. 'failed', 'partial')
        raw_offers = stats.get('raw_offers', 0)
        if raw_offers == 0:
            return "Nie pobrano żadnych ofert z OLX — możliwy problem z siecią lub zmiana struktury strony"
        
        # 3. Bardzo niski wynik przetwarzania
        processed = stats.get('processed', 0)
        if raw_offers > 0 and processed == 0:
            return f"Pobrano {raw_offers} ofert, ale żadna nie przeszła przetwarzania (brak adresów lub współrzędnych)"
        
        return "Skan zakończony z ostrzeżeniami — sprawdź logi"
    
    def _build_notification(
        self,
        ui_status: str,
        scan_time: Optional[str],
        new_count: int,
        disappeared_count,  # int lub None (brak danych ze starych skanów)
        errors: list,
    ) -> Dict:
        """
        Generuje gotowe teksty powiadomienia push.
        Aplikacja Android wyświetla notification.title i notification.body wprost,
        bez żadnej dodatkowej logiki.
        
        Format:
          success, nowe>0, znikłe>0: "✅ Skan 15:51 — +3 nowe / -2 znikły"
          success, nowe>0           : "✅ Skan 15:51 — 3 nowe mieszkania"
          success, znikłe>0         : "✅ Skan 15:51 — 2 znikły, brak nowych"
          success, brak zmian       : "✅ Skan 15:51 — brak zmian"
          warning                   : "⚠️ Skan 15:51 — zakończony z ostrzeżeniami"
          failed                    : "❌ Skan 15:51 — nie powiódł się"
        """
        time_label = f"Skan {scan_time}" if scan_time else "Skan"
        
        if ui_status == "success":
            if new_count > 0 and disappeared_count:
                title = f"✅ {time_label} — +{new_count} nowe / -{disappeared_count} znikły"
                body = (f"Pojawiło się {new_count} nowych, "
                        f"znikło {disappeared_count} ofert mieszkań w Lublinie")
            elif new_count > 0:
                title = f"✅ {time_label} — {new_count} {self._plural_mieszkania(new_count)}"
                body = f"Znaleziono {new_count} nowych ofert mieszkań w Lublinie"
            elif disappeared_count:
                title = f"✅ {time_label} — {disappeared_count} {self._plural_znikly(disappeared_count)}, brak nowych"
                body = f"Znikło {disappeared_count} ofert, żadnych nowych mieszkań"
            else:
                title = f"✅ {time_label} — brak zmian"
                body = "Skan zakończony, żadnych zmian w ofertach"
        
        elif ui_status == "warning":
            first_error = errors[0].get('message', '') if errors else ''
            title = f"⚠️ {time_label} — zakończony z ostrzeżeniami"
            body = first_error if first_error else "Sprawdź szczegóły w aplikacji"
        
        else:  # failed
            first_error = errors[0].get('message', '') if errors else 'Nieznany błąd'
            title = f"❌ {time_label} — nie powiódł się"
            body = first_error
        
        return {
            "title": title,
            "body": body,
        }
    
    def _format_scan_short(self, scan: Dict) -> Dict:
        """
        Skrócony format skanu dla pola recentScans w status.json.
        Tylko dane potrzebne do wyświetlenia paska historii w UI.
        """
        if not scan:
            return {}
        stats = scan.get('stats', {})
        errors = scan.get('errors', [])

        ui_status = "success"
        if scan.get('status') != 'completed':
            ui_status = "failed"
        elif errors:
            ui_status = "warning"

        return {
            "id": scan.get('timestamp', '')[:19].replace(':', '-'),
            "scanTimeFormatted": self._format_scan_time(scan.get('timestamp')),
            "uiStatus": ui_status,
            "newOffers": stats.get('new', 0),
            "disappearedOffers": self._disappeared_count(stats),  # spójne z „Znikło" w monitoringu
            "hasErrors": len(errors) > 0,
        }

    @staticmethod
    def _disappeared_count(stats: Dict):
        """
        Liczba ofert, które „znikły" — spójna z kolumną „Znikło" w dashboardzie monitoringu.

        Priorytet (jak w docs/monitoring.html):
          1. verification.confirmed_inactive — liczba potwierdzona po re-weryfikacji,
             bez fałszywych alarmów z niestabilnej paginacji OLX (właściwa wartość),
          2. disappeared — surowa liczba przeoczonych przez scraper (gdy brak weryfikacji),
          3. None — stary skan sprzed wdrożenia pola.
        """
        verification = stats.get('verification') or {}
        confirmed_inactive = verification.get('confirmed_inactive')
        if confirmed_inactive is not None:
            return confirmed_inactive
        return stats.get('disappeared', None)

    @staticmethod
    def _plural_mieszkania(n: int) -> str:
        """Polska odmiana słowa 'mieszkanie' dla liczby n."""
        if n == 1:
            return "nowe mieszkanie"
        if 2 <= n <= 4:
            return "nowe mieszkania"
        return "nowych mieszkań"

    @staticmethod
    def _plural_znikly(n: int) -> str:
        """Polska odmiana 'zniknął/znikły' dla liczby n."""
        if n == 1:
            return "zniknęło 1 ogłoszenie"
        if 2 <= n <= 4:
            return f"{n} ogłoszenia znikły"
        return f"{n} ogłoszeń znikło"
    
    def _calculate_next_scan_time(self) -> Optional[datetime]:
        """
        Oblicza przewidywany czas następnego skanu
        na podstawie harmonogramu (09:17, 15:17, 21:17 CET/CEST).
        """
        now = datetime.now(self.tz)
        today = now.date()
        
        for time_str in self.SCAN_SCHEDULE:
            hour, minute = map(int, time_str.split(':'))
            scan_time = self.tz.localize(
                datetime.combine(today, datetime.min.time().replace(hour=hour, minute=minute))
            )
            if scan_time > now:
                return scan_time
        
        # Jeśli wszystkie dzisiejsze skany minęły, zwróć pierwszy jutrzejszy
        tomorrow = today + timedelta(days=1)
        hour, minute = map(int, self.SCAN_SCHEDULE[0].split(':'))
        return self.tz.localize(
            datetime.combine(tomorrow, datetime.min.time().replace(hour=hour, minute=minute))
        )
    
    def _determine_system_status(self, last_scan: Optional[Dict], statistics: Dict) -> str:
        """
        Określa ogólny status systemu.
        
        Returns:
            operational - wszystko działa
            degraded - działa z błędami
            down - ostatni skan się nie powiódł
            unknown - brak danych
        """
        if not last_scan:
            return "unknown"
        
        if last_scan.get('status') != 'completed':
            return "down"
        
        if last_scan.get('errors'):
            return "degraded"
        
        # Sprawdź success rate z ostatnich skanów
        if statistics.get('success_rate', 100) < 80:
            return "degraded"
        
        return "operational"
    
    def _format_duration(self, seconds: Optional[float]) -> str:
        """Formatuje czas trwania do czytelnej postaci."""
        if seconds is None:
            return "N/A"
        
        minutes = int(seconds // 60)
        secs = int(seconds % 60)
        
        if minutes > 0:
            return f"{minutes}m {secs}s"
        return f"{secs}s"
    
    def _save_json(self, filename: str, data: Dict):
        """Zapisuje dane JSON do pliku."""
        filepath = self.output_dir / filename
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)


def main():
    """Główna funkcja - generuje wszystkie pliki API."""
    generator = APIGenerator()
    generator.generate_all()


if __name__ == "__main__":
    main()

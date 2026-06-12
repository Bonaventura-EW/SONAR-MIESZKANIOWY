# SONAR Mobile API Documentation

**Base URL:** `https://bonaventura-ew.github.io/SONAR-MIESZKANIOWY/api`

API jest statyczne (pliki JSON aktualizowane co skan), więc nie wymaga autentykacji.

---

## Endpoints

### 1. Status - `/api/status.json`

Aktualny status systemu z szczegółami ostatniego skanu.

**URL:** `https://bonaventura-ew.github.io/SONAR-MIESZKANIOWY/api/status.json`

**Response:**
```json
{
  "system": "sonar",
  "version": "1.0.0",
  "generatedAt": "2026-03-07T18:37:34.697847+01:00",
  
  "status": {
    "current": "operational",      // operational | degraded | down | unknown
    "isHealthy": true,             // dla szybkiego sprawdzenia w UI
    "hasErrors": false,
    "errorMessages": []
  },
  
  "lastScan": {
    "id": "2026-03-07T15-51-04",
    "timestamp": "2026-03-07T15:51:04.097760+01:00",
    "endTimestamp": "2026-03-07T15:55:57.738810+01:00",
    "durationSeconds": 293.64,
    "durationFormatted": "4m 53s",
    "uiStatus": "success",         // success | warning | failed
    "rawStatus": "completed",
    "offers": {
      "found": 459,
      "processed": 88,
      "new": 0,
      "updated": 88,
      "active": 109,
      "inactive": 37
    },
    "skipped": {
      "noAddress": 173,
      "noCoords": 193,
      "duplicates": 5
    },
    "errors": [],
    "hasErrors": false
  },
  
  "schedule": {
    "times": ["09:17", "15:17", "21:17"],
    "timezone": "Europe/Warsaw",
    "nextScanAt": "2026-03-07T21:17:00+01:00"
  },
  
  "statistics": {
    "totalScans": 32,
    "successRate": 96.9,
    "avgDurationSeconds": 270.35,
    "avgOffersFound": 361.5
  }
}
```

---

### 2. Historia - `/api/history.json`

Historia ostatnich 20 skanów.

**URL:** `https://bonaventura-ew.github.io/SONAR-MIESZKANIOWY/api/history.json`

**Response:**
```json
{
  "system": "sonar",
  "generatedAt": "2026-03-07T18:37:34+01:00",
  "count": 20,
  "scans": [
    {
      "id": "2026-03-07T15-51-04",
      "timestamp": "2026-03-07T15:51:04+01:00",
      "durationSeconds": 293.64,
      "uiStatus": "success",
      "offers": { ... },
      "hasErrors": false
    },
    // ... kolejne 19 skanów
  ]
}
```

---

### 3. Health Check - `/api/health.json`

Prosty health check do sprawdzenia czy API jest dostępne i aktualne.

**URL:** `https://bonaventura-ew.github.io/SONAR-MIESZKANIOWY/api/health.json`

**Response:**
```json
{
  "status": "ok",                  // ok | stale
  "timestamp": "2026-03-07T18:37:34+01:00",
  "lastScanAt": "2026-03-07T15:51:04+01:00",
  "hoursSinceLastScan": 2.8,
  "isFresh": true,                 // true jeśli < 12h od ostatniego skanu
  "systems": {
    "sonar": {
      "enabled": true,
      "lastStatus": "completed"
    },
    "szperacz": {
      "enabled": false,
      "lastStatus": null,
      "message": "Coming soon"
    }
  }
}
```

---

## Flutter Integration Example

```dart
import 'dart:convert';
import 'package:http/http.dart' as http;

class SonarApiClient {
  static const baseUrl = 'https://bonaventura-ew.github.io/SONAR-MIESZKANIOWY/api';
  
  /// Pobiera aktualny status systemu
  Future<SonarStatus> getStatus() async {
    final response = await http.get(
      Uri.parse('$baseUrl/status.json'),
      headers: {'Cache-Control': 'no-cache'},
    );
    
    if (response.statusCode == 200) {
      return SonarStatus.fromJson(jsonDecode(response.body));
    }
    throw Exception('Failed to load status');
  }
  
  /// Pobiera historię skanów
  Future<ScanHistory> getHistory() async {
    final response = await http.get(Uri.parse('$baseUrl/history.json'));
    
    if (response.statusCode == 200) {
      return ScanHistory.fromJson(jsonDecode(response.body));
    }
    throw Exception('Failed to load history');
  }
  
  /// Sprawdza czy API jest dostępne
  Future<bool> healthCheck() async {
    try {
      final response = await http.get(Uri.parse('$baseUrl/health.json'));
      if (response.statusCode == 200) {
        final data = jsonDecode(response.body);
        return data['status'] == 'ok';
      }
    } catch (e) {
      return false;
    }
    return false;
  }
}
```

---

## Powiadomienia - logika w aplikacji

### Sprawdzanie błędów skanu
```dart
void checkForErrors(SonarStatus status) {
  if (status.status.hasErrors) {
    showNotification(
      title: '⚠️ SONAR - Błąd skanu',
      body: status.status.errorMessages.join(', '),
    );
  }
}
```

### Powiadomienie o zakończeniu skanu
```dart
void notifyScanCompleted(SonarStatus status) {
  final scan = status.lastScan;
  showNotification(
    title: scan.uiStatus == 'success' ? '✅ SONAR' : '⚠️ SONAR',
    body: 'Skan zakończony: ${scan.offers.processed} ofert, '
          '${scan.offers.new_} nowych',
  );
}
```

---

## Harmonogram odświeżania

API jest aktualizowane po każdym skanie:
- **09:17** CET/CEST
- **15:17** CET/CEST
- **21:17** CET/CEST

Zalecana strategia polling w aplikacji:
- Co 5 minut w godzinach 09:10-09:40, 15:10-15:40, 21:10-21:40
- Co 30 minut w pozostałych godzinach
- Lub użyć `nextScanAt` do inteligentnego schedulowania

---

## CORS

GitHub Pages domyślnie obsługuje CORS, więc API można odpytywać z dowolnej domeny/aplikacji.

---

## Przyszłe rozszerzenia

1. **SZPERACZ** - drugi system monitoringu (pole `systems.szperacz` w health.json jest przygotowane)
2. **Push notifications** - webhook do Firebase Cloud Messaging
3. **Filtry** - parametry query dla history.json

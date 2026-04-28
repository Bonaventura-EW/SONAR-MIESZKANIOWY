# 📱 SONAR Mobile API

Statyczne REST API dla aplikacji mobilnych monitorujących system SONAR-POKOJOWY.

## 🔗 Base URL

```
https://bonaventura-ew.github.io/SONAR-POKOJOWY/api
```

---

## 📡 Endpointy

| Endpoint | Opis | Odświeżanie |
|----------|------|-------------|
| `/api/status.json` | Aktualny status + ostatni skan | Co skan |
| `/api/history.json` | Historia 20 ostatnich skanów | Co skan |
| `/api/health.json` | Health check systemu | Co skan |

---

## 1️⃣ Status (`/api/status.json`)

Główny endpoint - aktualny stan systemu i szczegóły ostatniego skanu.

```bash
curl https://bonaventura-ew.github.io/SONAR-POKOJOWY/api/status.json
```

### Response

```json
{
  "system": "sonar",
  "version": "1.0.0",
  "generatedAt": "2026-03-07T15:55:57+01:00",
  
  "status": {
    "current": "operational",
    "isHealthy": true,
    "hasErrors": false,
    "errorMessages": []
  },
  
  "lastScan": {
    "id": "2026-03-07T15-51-04",
    "timestamp": "2026-03-07T15:51:04+01:00",
    "endTimestamp": "2026-03-07T15:55:57+01:00",
    "durationSeconds": 293.64,
    "durationFormatted": "4m 53s",
    "uiStatus": "success",
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
    "times": ["09:00", "15:00", "21:00"],
    "timezone": "Europe/Warsaw",
    "nextScanAt": "2026-03-07T21:00:00+01:00"
  },
  
  "statistics": {
    "totalScans": 32,
    "successRate": 96.9,
    "avgDurationSeconds": 270.35,
    "avgOffersFound": 361.5
  }
}
```

### Pola statusu

| Pole | Wartości | Opis |
|------|----------|------|
| `status.current` | `operational` / `degraded` / `down` / `unknown` | Ogólny stan systemu |
| `status.isHealthy` | `true` / `false` | Szybki check dla UI |
| `lastScan.uiStatus` | `success` / `warning` / `failed` | Status ostatniego skanu |

---

## 2️⃣ Historia (`/api/history.json`)

Lista 20 ostatnich skanów (od najnowszego).

```bash
curl https://bonaventura-ew.github.io/SONAR-POKOJOWY/api/history.json
```

### Response

```json
{
  "system": "sonar",
  "generatedAt": "2026-03-07T15:55:57+01:00",
  "count": 20,
  "scans": [
    {
      "id": "2026-03-07T15-51-04",
      "timestamp": "2026-03-07T15:51:04+01:00",
      "durationSeconds": 293.64,
      "durationFormatted": "4m 53s",
      "uiStatus": "success",
      "offers": {
        "found": 459,
        "processed": 88,
        "new": 0,
        "active": 109
      },
      "hasErrors": false
    }
    // ... kolejne skany
  ]
}
```

---

## 3️⃣ Health Check (`/api/health.json`)

Prosty endpoint do sprawdzenia dostępności API.

```bash
curl https://bonaventura-ew.github.io/SONAR-POKOJOWY/api/health.json
```

### Response

```json
{
  "status": "ok",
  "timestamp": "2026-03-07T15:55:57+01:00",
  "lastScanAt": "2026-03-07T15:51:04+01:00",
  "hoursSinceLastScan": 2.8,
  "isFresh": true,
  "systems": {
    "sonar": {
      "enabled": true,
      "lastStatus": "completed"
    },
    "szperacz": {
      "enabled": false,
      "message": "Coming soon"
    }
  }
}
```

| Pole | Opis |
|------|------|
| `status` | `ok` = dane świeże, `stale` = dane starsze niż 12h |
| `isFresh` | `true` jeśli ostatni skan < 12h temu |

---

## ⏰ Harmonogram skanów

API jest aktualizowane automatycznie po każdym skanie:

| Czas (CET) | UTC (zima) | UTC (lato) |
|------------|------------|------------|
| 09:00 | 08:00 | 07:00 |
| 15:00 | 14:00 | 13:00 |
| 21:00 | 20:00 | 19:00 |

---

## 📲 Przykład Flutter

```dart
import 'dart:convert';
import 'package:http/http.dart' as http;

class SonarApi {
  static const _baseUrl = 
    'https://bonaventura-ew.github.io/SONAR-POKOJOWY/api';

  Future<Map<String, dynamic>> getStatus() async {
    final response = await http.get(
      Uri.parse('$_baseUrl/status.json'),
    );
    return jsonDecode(response.body);
  }

  Future<bool> isHealthy() async {
    try {
      final response = await http.get(
        Uri.parse('$_baseUrl/health.json'),
      );
      final data = jsonDecode(response.body);
      return data['status'] == 'ok';
    } catch (_) {
      return false;
    }
  }
}
```

### Sprawdzanie błędów (powiadomienia)

```dart
void checkScanStatus(Map<String, dynamic> status) {
  // Błędy skanu
  if (status['status']['hasErrors']) {
    final errors = status['status']['errorMessages'];
    showNotification('⚠️ Błąd SONAR', errors.join(', '));
  }
  
  // Status skanu
  final scan = status['lastScan'];
  final uiStatus = scan['uiStatus'];
  
  if (uiStatus == 'success') {
    showNotification(
      '✅ Skan zakończony',
      '${scan['offers']['processed']} ofert, ${scan['offers']['new']} nowych'
    );
  } else if (uiStatus == 'failed') {
    showNotification('❌ Skan nieudany', 'Sprawdź logi');
  }
}
```

---

## 🔄 Strategia pollingu

```dart
Duration getPollingInterval() {
  final now = DateTime.now();
  final hour = now.hour;
  final minute = now.minute;
  
  // Częstsze sprawdzanie w okolicach skanów (±10 min)
  final scanHours = [9, 15, 21];
  for (final scanHour in scanHours) {
    if (hour == scanHour - 1 && minute >= 50 ||
        hour == scanHour && minute <= 10) {
      return Duration(minutes: 2);
    }
  }
  
  // Normalny polling
  return Duration(minutes: 15);
}
```

---

## 🔒 CORS & Cache

- ✅ **CORS**: GitHub Pages obsługuje CORS - możesz odpytywać z dowolnej domeny
- ⚠️ **Cache**: Dodaj `?t=${timestamp}` do URL żeby ominąć cache przeglądarki

```dart
final url = '$_baseUrl/status.json?t=${DateTime.now().millisecondsSinceEpoch}';
```

---

## 🛣️ Roadmap

- [ ] **SZPERACZ** - drugi system monitoringu
- [ ] **Push notifications** - webhook do FCM
- [ ] **Filtry** - parametry dla history.json
- [ ] **WebSocket** - real-time updates (wymaga backendu)

---

## 📁 Pliki źródłowe

| Plik | Opis |
|------|------|
| `src/api_generator.py` | Generator plików JSON |
| `docs/api/*.json` | Wygenerowane pliki API |
| `.github/workflows/scanner.yml` | Automatyzacja (GitHub Actions) |

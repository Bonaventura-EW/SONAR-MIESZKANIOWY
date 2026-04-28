# 🎯 SONAR MIESZKANIOWY

**Automatyczny agent monitorujący oferty wynajmu mieszkań w Lublinie**

[![Scan Status](https://img.shields.io/badge/Skany-3x%20dziennie-brightgreen)](https://bonaventura-ew.github.io/SONAR-MIESZKANIOWY/)
[![GitHub Pages](https://img.shields.io/badge/Demo-Live-blue)](https://bonaventura-ew.github.io/SONAR-MIESZKANIOWY/)

> Status: 🚧 Świeżo zainicjowany. Pierwszy skan po włączeniu GitHub Actions / Pages — patrz sekcja "Pierwsze uruchomienie".

---

## 🌐 Demo na żywo (po włączeniu Pages)

| Strona | Opis |
|--------|------|
| **🗺️ Mapa ofert** | Interaktywna mapa z pinezkami |
| **📊 Analityka** | Wykresy i statystyki rynku |
| **📈 Monitoring** | Status systemu i historia skanów |
| **🔍 Analiza Rynku** | Lifespan/survival curve ofert |
| **📱 Mobile API** | JSON API dla aplikacji mobilnych |

---

## ✨ Funkcje (skopiowane 1:1 z SONAR-POKOJOWY)

### 🔄 Automatyczne skanowanie
- **3 skany dziennie** (09:00, 15:00, 21:00 CET)
- Scraping wszystkich stron OLX z ofertami **mieszkań na wynajem w Lublinie**
- Inteligentne pomijanie ofert bez zmian (oszczędność requestów)
- Wykrywanie duplikatów (95% podobieństwa)

### 🗺️ Interaktywna mapa
- Pinezki kolorowane według ceny (12-stopniowy gradient 0–5000+ zł)
- Filtry: zakres cenowy, aktywne/nieaktywne, typ oferty
- Wyszukiwarka po adresie
- Spiral offset dla nakładających się markerów (jeden adres = wiele ofert)

### 📊 Analityka rynku
- Średnie ceny w czasie
- Rozkład cenowy ofert
- Trendy: nowe vs wygasłe ogłoszenia
- Lifespan / survival curve ofert

### 📱 Mobile API (statyczne JSON-y)
- `/api/status.json` — aktualny status + ostatni skan
- `/api/history.json` — historia 20 ostatnich skanów
- `/api/health.json` — health check

---

## 🎨 Zakresy cenowe (12-stopniowy gradient)

| Kolor | Zakres |
|-------|--------|
| 🟢 Zielony | 0–1500 zł |
| 🟢 Jasna zieleń | 1501–1750 zł |
| 🟢 Limonkowy | 1751–2000 zł |
| 🟡 Żółty | 2001–2250 zł |
| 🟠 Pomarańczowy | 2251–3000 zł |
| 🔴 Czerwony | 3001–3500 zł |
| 🔴 Ciemnoczerwony | 3501–4000 zł |
| 🟣 Fioletowy | 4001–5000 zł |
| 🟣 Ciemny fiolet | 5001+ zł |

> Zakresy ustawione na podstawie rynku Lublin. Dokładne wartości warto przeskalować po pierwszym skanie — patrz `src/map_generator.py` → `PRICE_RANGES`.

---

## 🏗️ Architektura

```
SONAR-MIESZKANIOWY/
├── .github/workflows/
│   └── scanner.yml              # GitHub Actions - 3 skany dziennie
│
├── src/
│   ├── main.py                  # Główny agent
│   ├── scraper.py               # Scraping OLX (BASE_URL)
│   ├── address_parser.py        # Parsowanie adresów
│   ├── price_parser.py          # Parsowanie cen (JSON-LD priorytet)
│   ├── geocoder.py              # Geokodowanie (Nominatim)
│   ├── duplicate_detector.py    # Wykrywanie duplikatów
│   ├── offer_tagger.py          # Tagi: mieszkanie/kawalerka/pokój
│   ├── map_generator.py         # Generator data.json
│   ├── monitoring_generator.py  # Generator monitoring_data.json
│   ├── api_generator.py         # Generator Mobile API
│   └── scan_logger.py           # Logger skanów
│
├── data/                        # Źródło prawdy (pusta na start)
│   ├── offers.json
│   ├── scan_history.json
│   ├── geocoding_cache.json
│   └── removed_listings.json
│
├── docs/                        # GitHub Pages
│   ├── index.html               # Mapa
│   ├── analytics.html           # Analityka
│   ├── monitoring.html          # Monitoring
│   ├── market_analysis.html     # Analiza rynku
│   ├── api/                     # Mobile API
│   └── assets/                  # CSS + JS
│
├── BLUEPRINT.md                 # Pełna dokumentacja architektury
├── README.md                    # Ten plik
└── requirements.txt
```

📖 **Pełna dokumentacja techniczna:** [BLUEPRINT.md](./BLUEPRINT.md)

---

## 🚀 Pierwsze uruchomienie

### 1. Klonowanie i zależności
```bash
git clone https://github.com/Bonaventura-EW/SONAR-MIESZKANIOWY.git
cd SONAR-MIESZKANIOWY
pip install -r requirements.txt
```

### 2. Lokalny test (opcjonalny)
```bash
cd src
python main.py                   # pełny skan, ~5–10 min
python map_generator.py          # generuje docs/data.json
python api_generator.py          # generuje docs/api/*.json
cd ../docs
python -m http.server 8000       # http://localhost:8000
```

### 3. GitHub Pages
`Settings → Pages → Source: Deploy from a branch → main → /docs → Save`

URL produkcyjny: `https://bonaventura-ew.github.io/SONAR-MIESZKANIOWY/`

### 4. Pierwszy skan automatyczny
`Actions → SONAR MIESZKANIOWY Scanner → Run workflow → main`

Pierwszy skan ~10 min (cache geokodowania pusty). Następne ~5 min.

### 5. Weryfikacja
- `https://bonaventura-ew.github.io/SONAR-MIESZKANIOWY/api/status.json` — świeży scan
- Mapa: pinezki kolorowe, popup z opisem, filtry działają
- Monitoring: ostatni skan = success

---

## 🔧 Konfiguracja parametrów

| Parametr | Plik | Wartość |
|---|---|---|
| **URL źródłowy** | `src/scraper.py` → `BASE_URL` | `https://www.olx.pl/nieruchomosci/mieszkania/wynajem/lublin/` |
| **User-Agent Nominatim** | `src/geocoder.py` | `sonar-mieszkaniowy-lublin/1.0` |
| **Zakresy cen** | `src/map_generator.py` → `PRICE_RANGES` | 12 zakresów 0–5000+ |
| **Próg duplikatów** | `src/main.py` | `0.95` |
| **Cron** | `.github/workflows/scanner.yml` | `0 7,13,19 * * *` (UTC = 9/15/21 CEST) |
| **Bbox Lublina** | `src/geocoder.py` → `LUBLIN_BBOX` | lat 51.18–51.30, lon 22.42–22.68 |

---

## 🛣️ Roadmap

- [x] Etap 0: Setup + skopiowanie z SONAR-POKOJOWY + podmiany
- [ ] Etap 1: Pierwszy automatyczny skan + weryfikacja danych
- [ ] Etap 2: Tuning `PRICE_RANGES` na podstawie faktycznego rozkładu
- [ ] Etap A: Powiadomienia email (filtry per cena/dzielnica/słowa kluczowe)
- [ ] Etap B: Detekcja podejrzanych ofert + analiza historii cen
- [ ] Etap C: Heatmap cen + indeks wartości
- [ ] Etap D: Filtry słów kluczowych + ulubione (localStorage)
- [ ] Etap E: Dodatkowe źródła (Otodom, Gratka), PWA push

---

## 🔗 Linki

- **Pełna dokumentacja:** [BLUEPRINT.md](./BLUEPRINT.md)
- **Siostrzany projekt (referencja):** [SONAR-POKOJOWY](https://github.com/Bonaventura-EW/SONAR-POKOJOWY) (monitoring pokoi)
- **Live demo SONAR-POKOJOWY:** https://bonaventura-ew.github.io/SONAR-POKOJOWY/

---

## 📝 Licencja

MIT License — swobodne użycie i modyfikacja.

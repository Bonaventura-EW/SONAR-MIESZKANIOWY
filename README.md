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
| **Cron** | `.github/workflows/scanner.yml` | `0 7,13,19 * * *` UTC = 9/15/21 CEST¹ |
| **Bbox Lublina** | `src/geocoder.py` → `LUBLIN_BBOX` | lat 51.18–51.30, lon 22.42–22.68 |

¹ Faktyczne czasy uruchomienia mogą być opóźnione o 1–3h — patrz [Znane ograniczenia](#%EF%B8%8F-znane-ograniczenia).

---

## ⚠️ Znane ograniczenia

### Opóźnienia skanów schedulowanych
Cron jest ustawiony na **9:00 / 15:00 / 21:00 CEST** (UTC: 7/13/19), ale **GitHub Actions nie gwarantuje punktualnego uruchomienia** scheduled workflows na public repo. Oficjalna polityka GitHuba dopuszcza opóźnienia w okresach wzmożonego ruchu, a **pełne godziny (`0 * * * *`) to czas największej kolejki**, bo większość projektów ustawia takie same godziny.

**Obserwowane opóźnienia (maj 2026):** typowo 60–180 minut, ekstremalnie do ~220 min. Przykłady:

| Planowany start (CEST) | Faktyczny start | Opóźnienie |
|---|---|---|
| 09:00 | 11:45 | +2h 45 min |
| 15:00 | 17:42 | +2h 42 min |
| 21:00 | 22:48 | +1h 48 min |

**Co to oznacza w praktyce:**
- Sprawdzając mapę o 09:30, 15:30, 21:30 możesz nie zobaczyć jeszcze danych z planowanego skanu — to **nie awaria**, tylko skan czeka w kolejce GitHuba.
- Dokładny czas startu można sprawdzić w `Actions → SONAR MIESZKANIOWY Scanner`.
- Ostatni faktyczny czas skanu zawsze widać w `docs/api/status.json` → `last_scan`.

**Jak to obejść (jeśli komuś przeszkadza):**
- Manualne uruchomienie: `Actions → Run workflow → main` startuje **natychmiast** (workflow_dispatch nie ma opóźnień).
- Alternatywnie cron z minutami nieparzystymi (`23 7,13,19 * * *` = startujący o 7:23 UTC zamiast 7:00) — średnio krótsze kolejki. **W tym projekcie świadomie zostawiono pełne godziny** — opóźnienia są akceptowalne dla danych aktualizowanych 3×/dzień.

### Inne znane ograniczenia
- **Limity Nominatim** (geokodowanie OpenStreetMap): max ~1 request/sekundę, dlatego pierwszy skan trwa ~10 min. Cache w `data/geocoding_cache.json` redukuje to do ~5 min przy kolejnych skanach.
- **Brak adresów w meta-danych OLX** — parser polega na regex po opisie. Ok. 20–25% ofert nie ma jasno wskazanego adresu w treści (sam tytuł typu "Mieszkanie do wynajęcia") — te trafiają do warstwy "bez lokalizacji" zamiast na mapę.
- **OLX może zmienić HTML** — wtedy success rate spada poniżej 50%, co widać w `monitoring.html`. Krytyczne selektory są w `scraper.py` → `_extract_offers_from_page()`.

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

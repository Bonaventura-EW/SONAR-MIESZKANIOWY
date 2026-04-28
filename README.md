# 🎯 SONAR MIESZKANIOWY

**Automatyczny agent monitorujący oferty wynajmu mieszkań w Lublinie**

> Status: 🚧 Repo zainicjowane — kod jeszcze nie zaimplementowany.

---

## 📐 Pierwsze kroki

Pełna instrukcja architektury, logiki i decyzji projektowych znajduje się w pliku **[BLUEPRINT.md](./BLUEPRINT.md)**.

Blueprint jest ekstraktem z działającego siostrzanego projektu [SONAR-POKOJOWY](https://github.com/Bonaventura-EW/SONAR-POKOJOWY) (monitoring pokoi). Zawiera:

- Pełną architekturę (backend Python + frontend Leaflet/Chart.js)
- Fragmenty kodu wszystkich kluczowych modułów
- Strukturę danych (`offers.json`, `data.json`, API)
- Konfigurację GitHub Actions (cron 3×/dzień)
- **Lessons Learned** — 22 krytyczne pułapki do uniknięcia
- Krok-po-kroku checklist pierwszego uruchomienia (sekcja 10)

## 🔑 Jedyny placeholder do podmiany

Aby uruchomić nowy projekt, jedyną zewnętrzną wartością do ustalenia jest **URL listingu OLX** dla mieszkań na wynajem w Lublinie. Patrz `BLUEPRINT.md` → sekcja "PLACEHOLDER" (na początku pliku).

Sugerowany kandydat: `https://www.olx.pl/nieruchomosci/mieszkania/wynajem/lublin/`

## 🛣️ Roadmap

1. Skopiować strukturę z SONAR-POKOJOWY zgodnie z BLUEPRINT.md, sekcja 10 (Pierwsze uruchomienie).
2. Podmienić `BASE_URL` w `src/scraper.py` na URL mieszkań.
3. Zaktualizować `PRICE_RANGES` w `src/map_generator.py` (mieszkania ~2000–5000 zł).
4. Zmienić `user_agent` w `src/geocoder.py` na `sonar-mieszkaniowy-lublin/1.0`.
5. Wyczyścić `data/*.json`.
6. Pierwszy lokalny scan testowy.
7. Włączyć GitHub Pages + Actions.

## 🔗 Linki

- Blueprint: [BLUEPRINT.md](./BLUEPRINT.md)
- Siostrzany projekt (referencja): [SONAR-POKOJOWY](https://github.com/Bonaventura-EW/SONAR-POKOJOWY)
- Live demo SONAR-POKOJOWY: https://bonaventura-ew.github.io/SONAR-POKOJOWY/

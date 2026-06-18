# Mockupy — podstrona „Analiza cen wg metrażu"

20 poglądowych wariantów wizualnych nowej podstrony, która analizuje treść
ogłoszeń i pokazuje **ile kosztują mieszkania w zależności od metrażu** (cena
za m², przedziały cenowe, podział na dzielnice, mapy cieplne, trendy,
kalkulator). Cel: wybór jednej koncepcji do wdrożenia produkcyjnego.

## Podgląd

Otwórz **`index.html`** — galeria z miniaturami (żywe iframe) i opisem każdego
wariantu. Każdy mockup to samodzielny plik HTML (dane wbudowane inline), więc
można go też otworzyć bezpośrednio. Wykresy (Chart.js) ładowane z CDN —
do renderowania potrzebny internet.

## Skąd dane

Statystyki są **realne**, policzone z `data/offers.json` (cała historia ofert):

```bash
python3 docs/mockups/compute_stats.py   # data/offers.json -> docs/mockups/stats.json
python3 docs/mockups/generate.py        # stats.json -> 20× *.html + index.html
```

- Metraż (m²) i liczba pokoi: ekstrahowane **z treści opisów** regexem
  (`compute_stats.py`). Pokrycie metrażem ~63% bazy.
- Cena: pole `price.current` (z danych strukturalnych OLX).
- Dzielnica: dopasowanie nazw lubelskich dzielnic w opisie/adresie.

## Warianty

01 Klasyczny dashboard · 02 Dark Pro · 03 Glassmorphism · 04 Minimal/Raport ·
05 Sidebar · 06 Zakładki · 07 Heatmapa · 08 Kalkulator · 09 Magazyn ·
10 Mobilny · 11 Neumorphism · 12 TV/Kiosk · 13 Porównywarka dzielnic ·
14 Korelacja (scatter) · 15 Karty przedziałów · 16 Trend/Prognoza ·
17 Korporacyjny BI · 18 Pastel · 19 Terminal · 20 Mega dashboard.

> Po wyborze koncepcji: ekstrakcję metrażu/dzielnic warto przenieść do `src/`
> (np. nowy generator `area_price_generator.py` zasilający `docs/area_price_data.json`),
> tak jak pozostałe generatory w pipeline.

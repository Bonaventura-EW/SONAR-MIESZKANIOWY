"""Ścieżki do katalogów projektu, liczone względem lokalizacji tego pliku.

Wcześniej moduły miały zaszyte na sztywno ścieżki względne (`../data/...`),
więc działały TYLKO uruchamiane z katalogu `src/`. Tutaj kotwiczymy je do
`__file__`, dzięki czemu skrypty znajdują dane niezależnie od bieżącego
katalogu (np. odpalane z roota repo albo przez pytest).

Uwaga: importy między modułami (`from cid import ...`) nadal zakładają, że
`src/` jest na sys.path — to osobna sprawa od lokalizacji danych.
"""

from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent
ROOT_DIR = SRC_DIR.parent
DATA_DIR = ROOT_DIR / "data"
DOCS_DIR = ROOT_DIR / "docs"

# Najczęściej używane pliki danych — jako stringi (zgodne z dotychczasowymi
# domyślnymi argumentami, które przyjmowały str).
OFFERS_JSON = str(DATA_DIR / "offers.json")
REMOVED_JSON = str(DATA_DIR / "removed_listings.json")
GEOCODING_CACHE_JSON = str(DATA_DIR / "geocoding_cache.json")
SCAN_HISTORY_JSON = str(DATA_DIR / "scan_history.json")
SKIPPED_SAMPLE_JSON = str(DATA_DIR / "skipped_offers_sample.json")

DOCS_DATA_JSON = str(DOCS_DIR / "data.json")
DOCS_API_DIR = str(DOCS_DIR / "api")
DOCS_MONITORING_JSON = str(DOCS_DIR / "monitoring_data.json")
DOCS_TOP5_JSON = str(DOCS_DIR / "top5_data.json")
DOCS_SKIPPED_DEBUG_HTML = str(DOCS_DIR / "skipped_debug.html")
DOCS_AREA_PRICE_JSON = str(DOCS_DIR / "area_price_data.json")

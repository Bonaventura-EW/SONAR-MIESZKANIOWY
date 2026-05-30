"""Wspólna konfiguracja pytest — dokłada src/ do sys.path.

Moduły projektu (main, scraper, address_parser, ...) importują się nawzajem
po nazwie bez pakietu (np. `from cid import extract_cid`), bo normalnie są
uruchamiane z katalogu src/. Tu robimy to samo dla testów.
"""

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

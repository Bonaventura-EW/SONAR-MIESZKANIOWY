"""Atomowy zapis plików JSON.

FIX 2026-06-12: dotąd json.dump pisał bezpośrednio do pliku docelowego.
Przerwanie procesu w trakcie zapisu (timeout Actions, OOM) zostawiało
ucięty/uszkodzony plik — a main._load_database przy JSONDecodeError
zaczynał od PUSTEJ bazy, co groziło scommitowaniem utraty całej historii.

Wzorzec: zapis do pliku tymczasowego w tym samym katalogu + os.replace
(atomowe na POSIX i Windows). Plik docelowy jest zawsze albo stary, albo
nowy — nigdy w połowie zapisany.
"""

import json
import os
import tempfile
from pathlib import Path


def atomic_write_json(path, data, indent=2, ensure_ascii=False):
    """Zapisuje `data` jako JSON do `path` atomowo (tmp + os.replace)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        dir=str(path.parent), prefix=path.name + '.', suffix='.tmp'
    )
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=ensure_ascii, indent=indent)
        os.replace(tmp_path, path)
    except BaseException:
        # Sprzątanie tmp po nieudanym zapisie; plik docelowy nietknięty
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

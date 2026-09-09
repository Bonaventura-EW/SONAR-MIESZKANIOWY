#!/usr/bin/env python3
"""
Dzienny stan bazy — ŹRÓDŁO PRAWDY dla Indeksu podaży (`trend.html`).

Dlaczego ten plik w ogóle istnieje
----------------------------------
Indeks był wcześniej REKONSTRUOWANY wstecz z `offers.json`: dla dnia D liczba
ofert, których przedział `first_seen … last_seen` obejmował D (patrz
`trend_generator.build_series_reconstructed`). Ta metoda ma wadę nie do
naprawienia w samych danych ofert: oferta, która zniknęła 10.06 i wróciła 20.08,
ma w bazie JEDEN ciągły przedział życia (dat deaktywacji nikt nie zapisywał),
więc była liczona jako żywa przez cały czerwiec, lipiec i sierpień. Zawyżenie
maleje z wiekiem punktu (im starszy dzień, tym więcej reaktywacji zdążyło
zasypać jego dziury), więc prawy koniec wykresu ZAWSZE sztucznie opadał — wykres
mylił się nie tylko co do poziomu, ale i co do kierunku trendu. To port poprawki
z siostrzanego SONAR POKOJOWY (manifest `2026-09-03-measured-index-history`).

Co robimy zamiast
-----------------
Każdy skan dopisuje tu swój wynik: `active` = ile ofert ma w bazie `active=true`
po zakończeniu skanu. To ta sama liczba, którą widać w monitoringu i na mapie —
mierzona, nie odtwarzana. Wykres rysuje ją wprost, więc stary punkt nigdy się już
nie zmienia (rekonstrukcja rosła wstecz z każdym nowym skanem).

Konwencja dnia: `active` = MAKSIMUM z odczytów danego dnia. Skan częściowy
(blokada OLX) zaniża stan, więc bierzemy najpełniejszy obraz dnia — inaczej
przerwany scrape rysowałby się jak załamanie rynku. `record()` nigdy nie obniża
już zapisanej wartości. `scans` liczy wszystkie odczyty dnia (także niższe),
żeby dało się poznać dzień z jednym skanem zamiast trzech.

Dzień bez ani jednego skanu (awaria Actions) NIE MA tu wpisu i `daily_series()`
zwraca dla niego `None` — front rysuje lukę zamiast zmyślonego zera.

Historia sprzed wdrożenia jest odtworzona ze starszych rewizji
`data/scan_history.json` z historii gita — patrz `src/backfill_index_history.py`.
Te wpisy mają `backfilled: true`.
"""

import json
from datetime import date, datetime, timedelta
from pathlib import Path

import paths
from atomic_json import atomic_write_json

INDEX_HISTORY_JSON = str(paths.DATA_DIR / "index_history.json")

NOTE = ("Dzienny stan bazy: ile ofert ma active=true po skanie. Zrodlo prawdy dla "
        "Indeksu podazy (trend.html). active = maksimum z odczytow danego dnia "
        "(skan czesciowy nie moze zanizyc historii). Nie edytowac recznie.")


class IndexHistoryError(RuntimeError):
    """Plik istnieje, ale nie da się go odczytać (ucięty zapis, konflikt gita)."""


def _path(path=None) -> Path:
    return Path(path) if path else Path(INDEX_HISTORY_JSON)


def load(path=None, strict: bool = False) -> dict:
    """Cała zawartość pliku. Brak pliku = pusty szkielet.

    Plik, który ISTNIEJE, ale jest nieczytelny (ucięty zapis, ślady konfliktu
    gita), to co innego niż brak pliku: przy `strict=True` leci
    IndexHistoryError zamiast pustego szkieletu. Bez tego rozróżnienia
    `record()` zapisywałby na uszkodzonym pliku sam dzisiejszy dzień i kasował
    całą historię pomiaru w jednym zapisie.
    """
    fp = _path(path)
    try:
        with open(fp, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return {"note": NOTE, "days": {}}
    except (OSError, json.JSONDecodeError) as exc:
        if strict:
            raise IndexHistoryError(f"{fp}: {exc}") from exc
        return {"note": NOTE, "days": {}}
    if not isinstance(data, dict) or not isinstance(data.get("days"), dict):
        if strict:
            raise IndexHistoryError(f"{fp}: brak słownika 'days'")
        return {"note": NOTE, "days": {}}
    return data


def save(data: dict, path=None) -> None:
    """Zapis atomowy. NIE pozwala zastąpić niepustej historii pustą — taki zapis
    zawsze znaczy, że wołający czytał uszkodzony albo cudzy plik."""
    days = data.get("days") or {}
    if not days:
        # Pusty zapis wolno przepuścić tylko wtedy, gdy DA SIĘ udowodnić, że nie
        # ma czego stracić. Plik nieczytelny nie jest dowodem na pustkę.
        try:
            existing = load(path, strict=True).get("days") or {}
        except IndexHistoryError as exc:
            raise IndexHistoryError(
                f"odmowa zapisu pustki: nie da się odczytać istniejącej historii ({exc})") from exc
        if existing:
            raise IndexHistoryError(
                f"odmowa zapisu: {len(existing)} dni historii miałoby zniknąć")
    data["note"] = NOTE
    data["generated_at"] = datetime.now().astimezone().isoformat()
    data["days"] = {d: days[d] for d in sorted(days)}
    atomic_write_json(_path(path), data)


def record(active: int, timestamp: str = None, path=None) -> dict:
    """Dopisuje wynik skanu do dnia, który wynika z `timestamp`.

    Wartość dnia to maksimum z odczytów — skan częściowy (blokada OLX) nigdy nie
    obniży już zapisanej liczby.
    """
    if active is None:
        return {}
    ts = timestamp or datetime.now().astimezone().isoformat()
    try:
        day = datetime.fromisoformat(ts).date().isoformat()
    except (ValueError, TypeError):
        day = date.today().isoformat()

    try:
        data = load(path, strict=True)
    except IndexHistoryError as exc:
        # Lepiej zgubić jeden odczyt niż nadpisać historię pustką. Plik zostaje
        # nietknięty, żeby dało się go naprawić ręcznie (backfill albo git).
        print(f"   ⚠️  index_history.json nieczytelny — NIE zapisuję dnia ({exc})")
        return {}
    entry = data["days"].get(day) or {"active": 0, "scans": 0}
    entry["scans"] = entry.get("scans", 0) + 1
    if active > entry.get("active", 0):
        entry["active"] = active
        entry["ts"] = ts
    # dzień dotknięty przez żywy skan przestaje być odtworzony z historii gita
    entry.pop("backfilled", None)
    data["days"][day] = entry
    save(data, path)
    return entry


def daily_series(start: date = None, path=None):
    """[(date, active|None), ...] — kolejne dni od `start` (lub od pierwszego
    zapisanego) do ostatniego zapisanego. `None` = dzień bez skanu."""
    days = load(path)["days"]
    parsed = {}
    for key, entry in days.items():
        try:
            parsed[date.fromisoformat(key)] = entry.get("active")
        except (ValueError, TypeError):
            continue
    if not parsed:
        return []
    first = max(start, min(parsed)) if start else min(parsed)
    last = max(parsed)
    out, day = [], first
    while day <= last:
        out.append((day, parsed.get(day)))
        day += timedelta(days=1)
    return out


if __name__ == "__main__":
    series = daily_series()
    if not series:
        print("index_history.json: pusto (uruchom backfill_index_history.py)")
    else:
        measured = [(d, v) for d, v in series if v is not None]
        gaps = sum(1 for _, v in series if v is None)
        print(f"index_history.json: {len(series)} dni "
              f"({series[0][0]} → {series[-1][0]}), {gaps} luk")
        if measured:
            print(f"   ostatni pomiar: {measured[-1][1]} aktywnych ({measured[-1][0]})")

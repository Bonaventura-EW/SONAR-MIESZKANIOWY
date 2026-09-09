"""Testy MIERZONEGO Indeksu podaży (index_history) i jego wpięcia w trend_generator.

Port poprawki z siostrzanego SONAR POKOJOWY (manifest
`2026-09-03-measured-index-history`): główny Indeks czytamy z zapisanego stanu
bazy po skanie, a nie z rekonstrukcji wstecz z first_seen/last_seen.
"""

import json
from datetime import date, datetime

import pytest

import index_history as ih
import trend_generator as gen


def _fp(tmp_path):
    return str(tmp_path / "index_history.json")


# ── index_history: zapis dnia ────────────────────────────────────────────────

def test_record_takes_daily_maximum(tmp_path):
    """Skan częściowy (blokada OLX) nie może obniżyć już zapisanego dnia."""
    p = _fp(tmp_path)
    ih.record(800, timestamp="2026-06-01T09:17:00+02:00", path=p)
    ih.record(500, timestamp="2026-06-01T15:17:00+02:00", path=p)  # niższy odczyt
    ih.record(820, timestamp="2026-06-01T21:17:00+02:00", path=p)
    days = ih.load(p)["days"]
    assert days["2026-06-01"]["active"] == 820
    assert days["2026-06-01"]["scans"] == 3


def test_record_refuses_to_wipe_history_on_corrupt_file(tmp_path):
    """Uszkodzony plik nie może skasować historii — record() nic nie zapisuje."""
    p = _fp(tmp_path)
    ih.record(700, timestamp="2026-06-01T09:17:00+02:00", path=p)
    with open(p, "w", encoding="utf-8") as f:
        f.write("{ ucięty zapis")  # symulacja przerwanego zapisu / konfliktu gita
    assert ih.record(999, timestamp="2026-06-02T09:17:00+02:00", path=p) == {}
    # plik zostaje nietknięty (do naprawy ręcznej), a nie nadpisany pustką
    with open(p, "r", encoding="utf-8") as f:
        assert f.read().startswith("{ ucięty")


def test_daily_series_marks_missing_days_as_none(tmp_path):
    """Dzień bez ani jednego skanu = None (luka), nie zmyślone zero."""
    p = _fp(tmp_path)
    ih.record(700, timestamp="2026-06-01T09:17:00+02:00", path=p)
    ih.record(710, timestamp="2026-06-03T09:17:00+02:00", path=p)  # 02.06 brak skanu
    series = ih.daily_series(path=p)
    as_dict = dict(series)
    assert as_dict[date(2026, 6, 1)] == 700
    assert as_dict[date(2026, 6, 2)] is None
    assert as_dict[date(2026, 6, 3)] == 710


def test_daily_series_clamped_to_start(tmp_path):
    p = _fp(tmp_path)
    ih.record(500, timestamp="2026-05-10T09:17:00+02:00", path=p)
    ih.record(700, timestamp="2026-06-01T09:17:00+02:00", path=p)
    series = ih.daily_series(start=date(2026, 5, 20), path=p)
    assert series[0][0] == date(2026, 5, 20)


# ── trend_generator: pomiar zamiast rekonstrukcji ────────────────────────────

def _write(tmp_path, offers, index_days=None):
    """Buduje katalog danych z offers.json (+ opcjonalnie index_history.json)."""
    offers_path = tmp_path / "offers.json"
    with open(offers_path, "w", encoding="utf-8") as f:
        json.dump({"offers": offers}, f)
    if index_days:
        for day, active in index_days.items():
            ih.record(active, timestamp=f"{day}T09:17:00+02:00",
                      path=str(tmp_path / "index_history.json"))
    return str(offers_path)


def test_measured_series_reads_index_history(tmp_path):
    ih.record(742, timestamp="2026-06-01T09:17:00+02:00",
              path=str(tmp_path / "index_history.json"))
    series = gen.measured_series(str(tmp_path / "offers.json"))
    by_day = {datetime.fromtimestamp(ms / 1000).date(): v for ms, v in series}
    assert by_day[date(2026, 6, 1)] == 742


def test_generator_prefers_measured_over_reconstruction(tmp_path):
    """Gdy jest index_history.json, series = pomiar, index_source = 'measured'."""
    offers = [_off("2026-05-16", "2026-06-01", active=True)]
    inp = _write(tmp_path, offers, index_days={"2026-06-01": 999})
    out = tmp_path / "trend_data.json"
    assert gen.generate_trend_data(input_file=inp, output_file=str(out))
    data = json.load(open(out))
    assert data["index_source"] == "measured"
    # 999 pochodzi z pomiaru, a nie z rekonstrukcji (która dałaby 1)
    assert data["current"] == 999


def test_generator_falls_back_to_reconstruction(tmp_path):
    """Bez index_history.json spadamy na rekonstrukcję (świeży klon repo-brata)."""
    offers = [_off("2026-05-16", "2026-05-16", active=True)]
    inp = _write(tmp_path, offers)  # brak index_history.json
    out = tmp_path / "trend_data.json"
    assert gen.generate_trend_data(input_file=inp, output_file=str(out))
    data = json.load(open(out))
    assert data["index_source"] == "reconstructed"


def test_bands_scale_to_measured_index():
    """Udział pasm z rekonstrukcji, ale suma pasm = MIERZONA linia Indeksu.

    Rekonstrukcja dałaby 2 oferty żywe 25.05; podajemy zmierzony Indeks 500,
    więc bez skalowania suma pasm wyszłaby 2, a nie 500.
    """
    offers = [
        _returned("2026-05-16", "2026-05-25", ["2026-05-18"]),  # startuje pomiar
        _returned("2026-05-16", "2026-05-25", ["2026-05-21"]),
    ]
    day = date(2026, 5, 25)
    measured = [[gen._day_ms(day), 500]]
    bands = gen.build_bands(offers, index_series=measured)
    new = dict(bands["new"])[gen._day_ms(day)]
    react = dict(bands["react"])[gen._day_ms(day)]
    assert new + react == 500
    assert react > new  # obie oferty to recykling, więc pasmo recyklingu dominuje


def test_bands_without_index_series_stay_raw():
    """Bez index_series pasma zwracają surowe liczby rekonstrukcji (kompat.)."""
    offers = [
        _returned("2026-05-16", "2026-05-25", ["2026-05-18"]),
        _returned("2026-05-16", "2026-05-25", ["2026-05-21"]),
    ]
    bands = gen.build_bands(offers)
    series = {ms: v for ms, v in gen.build_series(offers)}
    for (ms, fresh), (_, recycled) in zip(bands["new"], bands["react"]):
        assert fresh + recycled == series[ms]


def _off(first_seen, last_seen, active=False):
    return {
        "first_seen": f"{first_seen}T10:00:00+02:00",
        "last_seen": f"{last_seen}T18:00:00+02:00",
        "active": active,
    }


def _returned(first_seen, last_seen, days, active=True, gap_h=48.0, src="rescrape"):
    offer = _off(first_seen, last_seen, active)
    offer["reactivation_dates"] = [
        {"at": f"{d}T12:00:00+02:00", "gap_h": gap_h, "src": src} for d in days
    ]
    offer["reactivated_at"] = offer["reactivation_dates"][-1]["at"]
    return offer

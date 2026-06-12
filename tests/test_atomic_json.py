"""Testy atomowego zapisu JSON i ochrony przed startem z pustej bazy.

FIX 2026-06-12: nieatomowy zapis + ciche "tworzę nowy" przy JSONDecodeError
groziły utratą całej bazy ofert (pusta baza scommitowana na main).
"""

import json
import os

import pytest

from atomic_json import atomic_write_json


class TestAtomicWriteJson:
    def test_writes_valid_json(self, tmp_path):
        target = tmp_path / "out.json"
        atomic_write_json(target, {"a": 1, "ż": "ółć"})
        data = json.loads(target.read_text(encoding="utf-8"))
        assert data == {"a": 1, "ż": "ółć"}

    def test_no_tmp_leftovers(self, tmp_path):
        target = tmp_path / "out.json"
        atomic_write_json(target, [1, 2, 3])
        assert [p.name for p in tmp_path.iterdir()] == ["out.json"]

    def test_failed_write_keeps_original_intact(self, tmp_path):
        target = tmp_path / "out.json"
        target.write_text('{"old": true}', encoding="utf-8")
        with pytest.raises(TypeError):
            atomic_write_json(target, {"bad": object()})  # nieserializowalne
        # Oryginał nietknięty, brak plików tymczasowych
        assert json.loads(target.read_text(encoding="utf-8")) == {"old": True}
        assert [p.name for p in tmp_path.iterdir()] == ["out.json"]

    def test_creates_parent_dirs(self, tmp_path):
        target = tmp_path / "a" / "b" / "out.json"
        atomic_write_json(target, {})
        assert target.exists()


class TestCorruptedDatabaseAborts:
    def test_load_database_raises_on_corrupted_file(self, tmp_path):
        from main import SonarMieszkaniowy
        corrupted = tmp_path / "offers.json"
        corrupted.write_text('{"offers": [{"id": "x"', encoding="utf-8")  # ucięty JSON
        removed = tmp_path / "removed.json"
        with pytest.raises(RuntimeError, match="Uszkodzony plik bazy"):
            SonarMieszkaniowy(data_file=str(corrupted), removed_file=str(removed))

    def test_missing_file_creates_empty_database(self, tmp_path):
        from main import SonarMieszkaniowy
        agent = SonarMieszkaniowy(
            data_file=str(tmp_path / "offers.json"),
            removed_file=str(tmp_path / "removed.json"),
        )
        assert agent.database == {"last_scan": None, "next_scan": None, "offers": []}

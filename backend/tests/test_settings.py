"""Tests for the persistent application settings (⚙️ Einstellungen)."""
import json

import pytest
from fastapi.testclient import TestClient

from backend.services import settings_service
from backend.services.settings_service import (
    get_setting,
    load_settings,
    settings_schema,
    update_settings,
)


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path, monkeypatch):
    path = tmp_path / "settings.json"
    monkeypatch.setenv("EBUCH_SETTINGS_PATH", str(path))
    return path


def test_defaults_when_no_file_exists():
    values = load_settings()
    assert values["table_resolve_max_cells"] == 6
    assert get_setting("table_resolve_max_cells") == 6


def test_update_persists_and_merges(isolated_settings):
    values = update_settings({"table_resolve_max_cells": 12})
    assert values["table_resolve_max_cells"] == 12
    on_disk = json.loads(isolated_settings.read_text(encoding="utf-8"))
    assert on_disk["table_resolve_max_cells"] == 12
    assert load_settings()["table_resolve_max_cells"] == 12


@pytest.mark.parametrize("bad", [-1, 10_000, "viele", 2.5, None])
def test_invalid_values_are_rejected(bad):
    with pytest.raises(ValueError):
        update_settings({"table_resolve_max_cells": bad})
    assert load_settings()["table_resolve_max_cells"] == 6


def test_unknown_keys_are_rejected():
    with pytest.raises(ValueError):
        update_settings({"does_not_exist": 1})


def test_corrupt_file_falls_back_to_defaults(isolated_settings):
    isolated_settings.write_text("{kaputt", encoding="utf-8")
    assert load_settings()["table_resolve_max_cells"] == 6


def test_schema_describes_each_setting_in_german():
    schema = {s["key"]: s for s in settings_schema()}
    entry = schema["table_resolve_max_cells"]
    assert entry["type"] == "integer"
    assert entry["default"] == 6
    assert entry["min"] == 0
    assert "Zellen" in entry["label"]
    assert entry["description"]


def test_settings_endpoints_roundtrip():
    from backend.main import app

    client = TestClient(app)
    res = client.get("/api/settings")
    assert res.status_code == 200
    data = res.json()
    assert data["values"]["table_resolve_max_cells"] == 6
    assert any(s["key"] == "table_resolve_max_cells" for s in data["schema"])

    res = client.put("/api/settings", json={"values": {"table_resolve_max_cells": 9}})
    assert res.status_code == 200
    assert res.json()["values"]["table_resolve_max_cells"] == 9
    assert client.get("/api/settings").json()["values"]["table_resolve_max_cells"] == 9

    res = client.put("/api/settings", json={"values": {"table_resolve_max_cells": -3}})
    assert res.status_code == 422
    assert client.get("/api/settings").json()["values"]["table_resolve_max_cells"] == 9


def test_standardisation_reads_threshold_from_settings(monkeypatch):
    import backend.services.llm_service as llm

    update_settings({"table_resolve_max_cells": 4})
    captured = {}

    class _Delta:
        content = "((1))\n\nText."

    class _Choice:
        delta = _Delta()

    class _Chunk:
        choices = [_Choice()]

    class _Client:
        class chat:
            class completions:
                @staticmethod
                def create(**kwargs):
                    captured["system"] = kwargs["messages"][0]["content"]
                    return [_Chunk()]

    monkeypatch.setattr(llm, "start_rapid_mlx", lambda: _Client())
    llm.standardise_markdown("((1))\n\nText.")
    assert "höchstens 4 Zellen" in captured["system"]
    assert settings_service.get_setting("table_resolve_max_cells") == 4

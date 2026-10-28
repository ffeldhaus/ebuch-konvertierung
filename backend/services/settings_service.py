"""Persistent application settings stored in assets/settings.json."""

from __future__ import annotations

import json
import logging
import os
import threading
from typing import Any, Final

from backend.services.models import SettingSchemaEntry

logger = logging.getLogger(__name__)

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_LOCK = threading.Lock()

_SCHEMA: Final[tuple[SettingSchemaEntry, ...]] = (
    SettingSchemaEntry(
        key="table_resolve_max_cells",
        type="integer",
        default=6,
        min=0,
        max=200,
        group="Übertragungsregeln",
        label="Tabellen auflösen bis … Zellen",
        description=(
            "Kleine Tabellen mit höchstens so vielen Zellen (alle Zellen inklusive Kopfzeile) werden "
            "nicht als <Tabelle> übertragen, sondern aufgelöst – eingeleitet mit "
            "„<Anmerkung> Die folgende Tabelle wurde aufgelöst. </Anmerkung>“. "
            "0 = nie auflösen."
        ),
    ),
)

_SCHEMA_BY_KEY: Final[dict[str, SettingSchemaEntry]] = {entry.key: entry for entry in _SCHEMA}


def settings_schema() -> list[dict[str, Any]]:
    """Return the serialisable schema definitions for all configurable settings.

    Returns:
        List of dictionary representations of each ``SettingSchemaEntry``.
    """
    return [entry.model_dump() for entry in _SCHEMA]


def defaults() -> dict[str, Any]:
    """Return a dictionary mapping every setting key to its default value.

    Returns:
        Mapping of setting keys to their default values.
    """
    return {entry.key: entry.default for entry in _SCHEMA}


def settings_path() -> str:
    """Resolve the filesystem path to the persistent settings JSON file.

    Returns:
        Path from ``EBUCH_SETTINGS_PATH`` if set, otherwise ``assets/settings.json``.
    """
    return os.environ.get("EBUCH_SETTINGS_PATH") or os.path.join(_PROJECT_ROOT, "assets", "settings.json")


def _validate(key: str, value: Any) -> Any:
    """Validate a single setting key and value against its schema entry.

    Args:
        key: Setting identifier to validate.
        value: Candidate value to check against type and range bounds.

    Returns:
        The validated setting value.

    Raises:
        ValueError: If the key is unknown, the type is unsupported, or the value is invalid.
    """
    schema = _SCHEMA_BY_KEY.get(key)
    if schema is None:
        raise ValueError(f"Unbekannte Einstellung: {key}")
    if schema.type == "integer":
        # bool is a subclass of int – reject it explicitly, as well as floats/strings.
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{schema.label}: ganze Zahl erwartet")
        if value < schema.min or value > schema.max:
            raise ValueError(f"{schema.label}: erlaubt sind {schema.min}–{schema.max}")
        return value
    raise ValueError(f"Nicht unterstützter Einstellungstyp: {schema.type}")


def _read_file() -> dict[str, Any]:
    """Read raw key-value pairs from the settings JSON file on disk.

    Returns:
        Parsed JSON object if the file exists and is valid, or an empty dict on missing/corrupt files.
    """
    path = settings_path()
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError) as ex:
        logger.warning(f"Einstellungen konnten nicht gelesen werden ({path}): {ex} – verwende Standardwerte.")
        return {}


def load_settings() -> dict[str, Any]:
    """Load current settings by overlaying valid stored values onto schema defaults.

    Returns:
        Complete mapping of setting keys to validated effective values.
    """
    values = defaults()
    for key, value in _read_file().items():
        try:
            values[key] = _validate(key, value)
        except ValueError:
            logger.warning(f"Ignoriere ungültige gespeicherte Einstellung {key}={value!r}")
    return values


def get_setting(key: str) -> Any:
    """Retrieve the current effective value for a single setting key.

    Args:
        key: Setting identifier to look up.

    Returns:
        Effective validated value for ``key``.

    Raises:
        KeyError: If ``key`` is not defined in the settings schema.
    """
    return load_settings()[key]


def update_settings(partial: dict[str, Any]) -> dict[str, Any]:
    """Validate and atomically persist a partial dictionary of setting updates.

    Args:
        partial: Mapping of setting keys to new candidate values.

    Returns:
        Full dictionary of effective settings after applying the update.

    Raises:
        ValueError: If any key in ``partial`` is unknown or its value fails validation.
    """
    validated = {key: _validate(key, value) for key, value in (partial or {}).items()}
    with _LOCK:
        values = load_settings()
        values.update(validated)
        path = settings_path()
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(values, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    logger.info(f"Einstellungen gespeichert: {validated}")
    return values

"""Fachliche Einstellungen in der Datenbank (über die Oberfläche änderbar)."""

from __future__ import annotations

from typing import Any

from . import db

DEFAULTS: dict[str, Any] = {
    # observe: nur analysieren und protokollieren, nichts in Drive verändern (Standard)
    # review:  jede Ablage muss bestätigt werden
    # auto:    Ablage ab Schwellenwert automatisch (erst nach erfolgreichem Testlauf)
    "processing_mode": "observe",
    "auto_threshold": 0.95,
    "suggest_threshold": 0.75,
    # KI-Entscheidungen ohne Regel werden auf diesen Wert gedeckelt, bis die Schwellen
    # anhand realer Ergebnisse kalibriert wurden (Standard: immer Bestätigung).
    "ai_confidence_cap": 0.94,
    "allow_external_ai": False,
    "ai_provider": None,  # {"kind","base_url","model","has_key"}
    "filename_template": "{document_date}_{sender}_{document_type}_{reference}",
    "original_strategy": "original_only",  # original_only | original_plus_derivative | derivative_only
    "review_sensitive": True,
    "test_run_ok": False,
    "setup_completed": False,
    "default_archive_account_id": None,
}


def get(key: str) -> Any:
    return db.get_setting(key, DEFAULTS.get(key))


def set(key: str, value: Any) -> None:  # noqa: A001
    if key not in DEFAULTS:
        raise KeyError(key)
    db.set_setting(key, value)


def all_settings() -> dict[str, Any]:
    return {k: get(k) for k in DEFAULTS}

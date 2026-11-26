"""Laufzeitkonfiguration.

Quellen (aufsteigende Priorität):
1. Standardwerte in :class:`Settings`
2. ``/data/options.json`` (vom Home Assistant Supervisor aus den App-Optionen erzeugt)
3. Umgebungsvariablen ``LORZDMS_<NAME>`` (für Docker/Coolify und Tests)

Fachliche Einstellungen, die über die Oberfläche geändert werden (Verarbeitungsmodus,
Schwellenwerte, KI-Provider), liegen in der Datenbank (Tabelle ``settings``).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any


def _coerce(value: str, target: Any) -> Any:
    if isinstance(target, bool):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    if isinstance(target, int):
        return int(value)
    if isinstance(target, float):
        return float(value)
    return value


@dataclass
class Settings:
    data_dir: Path = Path("/data")
    share_dir: Path = Path("/share/lorzdms")
    log_level: str = "info"
    # Netzwerk / Authentifizierung
    listen_host: str = "0.0.0.0"
    listen_port: int = 8099
    trusted_proxy: str = "172.30.32.2"
    # Nur für lokale Entwicklung: fester Benutzer ohne Ingress. Niemals in Produktion.
    dev_user: str = ""
    # Ressourcen
    ocr_max_parallel: int = 1
    ocr_timeout_seconds: int = 900
    ocr_languages: str = "deu+eng"
    max_file_size_mb: int = 50
    max_image_pixels: int = 80_000_000
    min_free_disk_mb: int = 500
    max_load_per_cpu: float = 1.5
    processing_window: str = ""  # z. B. "22:00-06:00" für Massenimporte
    # Quellen
    local_inbox_enabled: bool = True
    local_inbox_after_success: str = "move"  # move | keep
    scan_interval_seconds: int = 30
    # Google OAuth
    oauth_redirect_uri: str = "http://127.0.0.1:8765/oauth2callback"
    extra: dict = field(default_factory=dict)

    # abgeleitete Pfade -------------------------------------------------
    @property
    def db_path(self) -> Path:
        return self.data_dir / "database" / "lorzdms.sqlite3"

    @property
    def snapshot_path(self) -> Path:
        return self.data_dir / "database" / "snapshot.sqlite3"

    @property
    def secrets_dir(self) -> Path:
        return self.data_dir / "secrets"

    @property
    def temp_dir(self) -> Path:
        return self.data_dir / "temp"

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / "cache"

    @property
    def quarantine_dir(self) -> Path:
        return self.data_dir / "quarantine"

    @property
    def inbox_dir(self) -> Path:
        return self.share_dir / "inbox"

    @property
    def processed_dir(self) -> Path:
        return self.share_dir / "processed"

    def ensure_dirs(self) -> None:
        for p in (
            self.db_path.parent,
            self.secrets_dir,
            self.temp_dir,
            self.cache_dir,
            self.quarantine_dir,
        ):
            p.mkdir(parents=True, exist_ok=True)
        os.chmod(self.secrets_dir, 0o700)
        if self.local_inbox_enabled:
            try:
                self.inbox_dir.mkdir(parents=True, exist_ok=True)
                self.processed_dir.mkdir(parents=True, exist_ok=True)
            except OSError:
                # /share ist ggf. nicht gemappt (z. B. Coolify ohne Volume)
                pass


def load_settings(options_path: str | None = None) -> Settings:
    s = Settings()
    names = {f.name: f for f in fields(Settings)}
    env_data = os.environ.get("LORZDMS_DATA_DIR")
    if env_data:
        s.data_dir = Path(env_data)
    opt_file = Path(options_path) if options_path else s.data_dir / "options.json"
    if opt_file.is_file():
        try:
            opts = json.loads(opt_file.read_text("utf-8"))
        except (OSError, json.JSONDecodeError):
            opts = {}
        for key, value in opts.items():
            if key in names and key not in {"data_dir", "extra"}:
                setattr(s, key, value)
            else:
                s.extra[key] = value
    for name in names:
        env_val = os.environ.get(f"LORZDMS_{name.upper()}")
        if env_val is None or name in {"extra"}:
            continue
        current = getattr(s, name)
        if isinstance(current, Path):
            setattr(s, name, Path(env_val))
        else:
            setattr(s, name, _coerce(env_val, current))
    return s


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = load_settings()
    return _settings


def set_settings(s: Settings) -> None:
    """Für Tests: Einstellungen ersetzen."""
    global _settings
    _settings = s

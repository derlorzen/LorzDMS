"""Verschlüsselung gespeicherter Zugangsdaten (OAuth-Tokens, API-Keys).

Ein zufälliger Hauptschlüssel liegt in ``/data/secrets/master.key`` (Rechte 0600) und wird
beim ersten Start erzeugt. Er ist Teil des Home-Assistant-Backups, damit verschlüsselte
Tokens nach einer Wiederherstellung lesbar bleiben. Ohne Schlüssel sind die Daten in der
Datenbank wertlos.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from . import db

_fernet: Fernet | None = None


def init(secrets_dir: Path) -> None:
    global _fernet
    secrets_dir.mkdir(parents=True, exist_ok=True)
    key_file = secrets_dir / "master.key"
    if not key_file.exists():
        key = Fernet.generate_key()
        fd = os.open(str(key_file), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as fh:
            fh.write(key)
    os.chmod(key_file, 0o600)
    _fernet = Fernet(key_file.read_bytes().strip())


def _f() -> Fernet:
    if _fernet is None:
        raise RuntimeError("Kryptografie nicht initialisiert")
    return _fernet


def encrypt(data: bytes) -> bytes:
    return _f().encrypt(data)


def decrypt(token: bytes) -> bytes:
    return _f().decrypt(token)


def put_secret(key: str, value: Any) -> None:
    blob = encrypt(json.dumps(value).encode("utf-8"))
    db.execute(
        "INSERT INTO secrets(key, ciphertext, updated_at) VALUES (?,?,?) "
        "ON CONFLICT(key) DO UPDATE SET ciphertext=excluded.ciphertext, updated_at=excluded.updated_at",
        (key, blob, db.utcnow()),
    )


def get_secret(key: str, default: Any = None) -> Any:
    row = db.one("SELECT ciphertext FROM secrets WHERE key=?", (key,))
    if row is None:
        return default
    try:
        return json.loads(decrypt(row[0]).decode("utf-8"))
    except InvalidToken as exc:  # Schlüssel passt nicht (z. B. Backup ohne secrets/)
        raise RuntimeError(f"Geheimnis '{key}' kann nicht entschlüsselt werden") from exc


def delete_secret(key: str) -> None:
    db.execute("DELETE FROM secrets WHERE key=?", (key,))


def mask(value: str | None) -> str:
    if not value:
        return ""
    return value[:4] + "…" if len(value) > 8 else "•••"

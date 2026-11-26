"""Gemeinsame Initialisierung für Web- und Worker-Prozess."""

from __future__ import annotations

import logging

from . import crypto, db
from .config import get_settings
from .sources import intake

log = logging.getLogger("lorzdms")


def init(role: str) -> None:
    s = get_settings()
    logging.basicConfig(
        level=getattr(logging, s.log_level.upper(), logging.INFO),
        format=f"%(asctime)s %(levelname)s [{role}] %(name)s: %(message)s",
    )
    s.ensure_dirs()
    if role == "web":
        status = db.restore_if_needed(s.db_path, s.snapshot_path)
        if status == "restored":
            log.warning("Datenbank fehlte oder war beschädigt – aus Backup-Snapshot wiederhergestellt")
        elif status == "corrupt-no-snapshot":
            raise SystemExit("Datenbank beschädigt und kein Snapshot vorhanden – Start abgebrochen")
    db.configure(s.db_path)
    applied = db.migrate()
    if applied:
        log.info("Migrationen angewendet: %s", ", ".join(applied))
    crypto.init(s.secrets_dir)
    intake.ensure_builtin_sources()

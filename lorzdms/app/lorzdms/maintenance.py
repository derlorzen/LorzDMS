"""Kommandozeilenwerkzeuge: ``python -m lorzdms.maintenance <befehl>``.

- ``backup-pre``: konsistenten Datenbank-Snapshot für das HA-Backup schreiben
- ``init``: Start-Initialisierung (Wiederherstellung aus Snapshot, Migrationen)
- ``check``: Integritätsprüfung
"""

from __future__ import annotations

import sys

from . import db
from .config import get_settings


def main(argv: list[str]) -> int:
    s = get_settings()
    cmd = argv[0] if argv else "check"
    if cmd == "init":
        from . import bootstrap

        bootstrap.init(role="web")
        print("Initialisierung abgeschlossen")
        return 0
    if cmd == "backup-pre":
        db.configure(s.db_path)
        db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        db.snapshot(s.snapshot_path)
        print(f"Snapshot geschrieben: {s.snapshot_path}")
        return 0
    if cmd == "check":
        ok = db.integrity_ok(s.db_path)
        print("ok" if ok else "FEHLER")
        return 0 if ok else 1
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

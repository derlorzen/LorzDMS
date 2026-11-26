"""SQLite-Zugriff (WAL-Modus) und Migrationen.

Jeder Thread erhält eine eigene Verbindung. Schreibtransaktionen mit konkurrierenden
Prozessen (Web + Worker) werden über ``busy_timeout`` serialisiert; kritische Abschnitte
(Job-Claim) nutzen ``BEGIN IMMEDIATE``.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from importlib import resources
from pathlib import Path
from typing import Any, Iterator

_local = threading.local()
_db_path: Path | None = None


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def configure(path: Path) -> None:
    global _db_path
    _db_path = Path(path)
    close()


def _connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=30, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def conn() -> sqlite3.Connection:
    if _db_path is None:
        raise RuntimeError("Datenbank nicht konfiguriert")
    c = getattr(_local, "conn", None)
    if c is None or getattr(_local, "path", None) != _db_path:
        c = _connect(_db_path)
        _local.conn = c
        _local.path = _db_path
    return c


def close() -> None:
    c = getattr(_local, "conn", None)
    if c is not None:
        c.close()
        _local.conn = None


@contextmanager
def tx(immediate: bool = False) -> Iterator[sqlite3.Connection]:
    c = conn()
    if c.in_transaction:
        # verschachtelt: äußere Transaktion verwenden
        yield c
        return
    c.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
    try:
        yield c
    except BaseException:
        c.execute("ROLLBACK")
        raise
    else:
        c.execute("COMMIT")


def query(sql: str, params: Any = ()) -> list[sqlite3.Row]:
    return conn().execute(sql, params).fetchall()


def one(sql: str, params: Any = ()) -> sqlite3.Row | None:
    return conn().execute(sql, params).fetchone()


def execute(sql: str, params: Any = ()) -> sqlite3.Cursor:
    return conn().execute(sql, params)


def row_to_dict(row: sqlite3.Row | None, json_fields: tuple[str, ...] = ()) -> dict | None:
    if row is None:
        return None
    d = dict(row)
    for f in json_fields:
        if f in d and isinstance(d[f], str):
            try:
                d[f] = json.loads(d[f])
            except json.JSONDecodeError:
                pass
    return d


# Migrationen -----------------------------------------------------------------

def _migration_files() -> list[tuple[int, str, str]]:
    out = []
    pkg = resources.files("lorzdms.migrations")
    for entry in pkg.iterdir():
        name = entry.name
        if name.endswith(".sql") and name[:4].isdigit():
            out.append((int(name[:4]), name, entry.read_text("utf-8")))
    return sorted(out)


def migrate() -> list[str]:
    c = conn()
    c.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL)"
    )
    applied = {r[0] for r in c.execute("SELECT version FROM schema_migrations")}
    done = []
    for version, name, sql in _migration_files():
        if version in applied:
            continue
        # executescript committet implizit; daher eigene Transaktion um das Skript
        c.execute("BEGIN IMMEDIATE")
        try:
            for statement in _split_sql(sql):
                c.execute(statement)
            c.execute(
                "INSERT INTO schema_migrations(version, name, applied_at) VALUES (?,?,?)",
                (version, name, utcnow()),
            )
            c.execute("COMMIT")
        except BaseException:
            c.execute("ROLLBACK")
            raise
        done.append(name)
    return done


def _split_sql(sql: str) -> list[str]:
    statements, buf = [], []
    for line in sql.splitlines():
        stripped = line.strip()
        if stripped.startswith("--") or not stripped:
            continue
        buf.append(line)
        candidate = "\n".join(buf)
        if stripped.endswith(";") and sqlite3.complete_statement(candidate):
            statements.append(candidate)
            buf = []
    if buf and "\n".join(buf).strip():
        statements.append("\n".join(buf))
    return statements


# Einstellungen ---------------------------------------------------------------

def get_setting(key: str, default: Any = None) -> Any:
    row = one("SELECT value FROM settings WHERE key=?", (key,))
    if row is None:
        return default
    return json.loads(row[0])


def set_setting(key: str, value: Any) -> None:
    execute(
        "INSERT INTO settings(key, value, updated_at) VALUES (?,?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
        (key, json.dumps(value), utcnow()),
    )


def audit(action: str, user_id: int | None = None, target: str | None = None, **details: Any) -> None:
    execute(
        "INSERT INTO audit_log(ts, user_id, action, target, details) VALUES (?,?,?,?,?)",
        (utcnow(), user_id, action, target, json.dumps(details) if details else None),
    )


# Backup / Wiederherstellung --------------------------------------------------

def snapshot(target: Path) -> None:
    """Konsistente Kopie über die SQLite-Backup-API (auch bei laufendem Betrieb)."""
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".tmp")
    if tmp.exists():
        tmp.unlink()
    src = _connect(_db_path) if _db_path else conn()
    try:
        dst = sqlite3.connect(str(tmp))
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()
    tmp.replace(target)


def integrity_ok(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        c = sqlite3.connect(str(path))
        try:
            res = c.execute("PRAGMA integrity_check").fetchone()
            return bool(res) and res[0] == "ok"
        finally:
            c.close()
    except sqlite3.DatabaseError:
        return False


def restore_if_needed(db_path: Path, snapshot_path: Path) -> str:
    """Beim Start: fehlende oder beschädigte Datenbank aus dem Snapshot wiederherstellen.

    Rückgabe: 'ok', 'restored', 'new' oder 'corrupt-no-snapshot'.
    """
    if integrity_ok(db_path):
        return "ok"
    if snapshot_path.exists() and integrity_ok(snapshot_path):
        if db_path.exists():
            broken = db_path.with_name(db_path.name + f".broken-{datetime.now():%Y%m%d%H%M%S}")
            db_path.replace(broken)
        for suffix in ("-wal", "-shm"):
            side = Path(str(db_path) + suffix)
            if side.exists():
                side.unlink()
        shutil.copy2(snapshot_path, db_path)
        return "restored"
    if db_path.exists():
        return "corrupt-no-snapshot"
    return "new"

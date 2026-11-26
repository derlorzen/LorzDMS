"""Persistente Job-Queue auf SQLite.

- Priorität: kleinere Zahl = wichtiger (neue Dokumente 100, Massenimport 500).
- Lease: ein laufender Job gehört einem Worker bis ``lease_until``; nach Absturz wird er
  von :func:`recover_expired` wieder freigegeben (Wiederanlauf).
- Fehler: exponentieller Backoff mit Jitter, nach ``max_attempts`` Status ``dead``
  (Dead-Letter-Queue), manuell wieder anstoßbar.
- ``dedupe_key``: höchstens ein offener Job pro Schlüssel.
"""

from __future__ import annotations

import json
import random
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

from . import db

BASE_DELAY = 30
MAX_DELAY = 3600


def _ts(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def enqueue(
    kind: str,
    payload: dict | None = None,
    *,
    priority: int = 100,
    dedupe_key: str | None = None,
    delay_seconds: int = 0,
    max_attempts: int = 5,
) -> int | None:
    """Job einreihen. Gibt die Job-ID zurück oder ``None``, wenn bereits ein offener Job
    mit demselben ``dedupe_key`` existiert."""
    now = _now()
    try:
        cur = db.execute(
            "INSERT INTO jobs(kind, payload, priority, state, attempts, max_attempts, run_after, dedupe_key, created_at, updated_at)"
            " VALUES (?,?,?,?,0,?,?,?,?,?)",
            (
                kind,
                json.dumps(payload or {}),
                priority,
                "queued",
                max_attempts,
                _ts(now + timedelta(seconds=delay_seconds)),
                dedupe_key,
                _ts(now),
                _ts(now),
            ),
        )
        return cur.lastrowid
    except sqlite3.IntegrityError:
        return None


def claim(worker: str, *, lease_seconds: int = 1800, max_priority: int | None = None) -> dict | None:
    now = _now()
    with db.tx(immediate=True) as c:
        sql = "SELECT id FROM jobs WHERE state='queued' AND run_after<=?"
        params: list[Any] = [_ts(now)]
        if max_priority is not None:
            sql += " AND priority<=?"
            params.append(max_priority)
        sql += " ORDER BY priority ASC, run_after ASC, id ASC LIMIT 1"
        row = c.execute(sql, params).fetchone()
        if row is None:
            return None
        c.execute(
            "UPDATE jobs SET state='running', attempts=attempts+1, worker=?, lease_until=?, updated_at=? WHERE id=?",
            (worker, _ts(now + timedelta(seconds=lease_seconds)), _ts(now), row[0]),
        )
        job = c.execute("SELECT * FROM jobs WHERE id=?", (row[0],)).fetchone()
    d = dict(job)
    d["payload"] = json.loads(d["payload"])
    return d


def extend_lease(job_id: int, seconds: int = 1800) -> None:
    db.execute(
        "UPDATE jobs SET lease_until=?, updated_at=? WHERE id=? AND state='running'",
        (_ts(_now() + timedelta(seconds=seconds)), _ts(_now()), job_id),
    )


def complete(job_id: int) -> None:
    now = _ts(_now())
    db.execute(
        "UPDATE jobs SET state='done', lease_until=NULL, last_error=NULL, finished_at=?, updated_at=? WHERE id=?",
        (now, now, job_id),
    )


def backoff_seconds(attempts: int) -> int:
    delay = min(MAX_DELAY, BASE_DELAY * (2 ** max(0, attempts - 1)))
    return int(delay * random.uniform(0.8, 1.2))


def fail(job_id: int, error: str, *, retryable: bool = True) -> str:
    """Fehler verbuchen. Rückgabe: neuer Status ('queued' oder 'dead')."""
    row = db.one("SELECT attempts, max_attempts FROM jobs WHERE id=?", (job_id,))
    if row is None:
        return "missing"
    now = _now()
    error = error[:2000]
    if retryable and row["attempts"] < row["max_attempts"]:
        db.execute(
            "UPDATE jobs SET state='queued', lease_until=NULL, worker=NULL, last_error=?, run_after=?, updated_at=? WHERE id=?",
            (error, _ts(now + timedelta(seconds=backoff_seconds(row["attempts"]))), _ts(now), job_id),
        )
        return "queued"
    db.execute(
        "UPDATE jobs SET state='dead', lease_until=NULL, last_error=?, finished_at=?, updated_at=? WHERE id=?",
        (error, _ts(now), _ts(now), job_id),
    )
    return "dead"


def defer(job_id: int, seconds: int, reason: str) -> None:
    """Job ohne Fehlversuch verschieben (z. B. Ressourcenknappheit)."""
    now = _now()
    db.execute(
        "UPDATE jobs SET state='queued', attempts=MAX(attempts-1,0), lease_until=NULL, worker=NULL, last_error=?, run_after=?, updated_at=? WHERE id=?",
        (reason, _ts(now + timedelta(seconds=seconds)), _ts(now), job_id),
    )


def recover_expired() -> int:
    now = _ts(_now())
    cur = db.execute(
        "UPDATE jobs SET state='queued', worker=NULL, lease_until=NULL, last_error='lease expired (Neustart/Absturz)', updated_at=?"
        " WHERE state='running' AND lease_until < ?",
        (now, now),
    )
    return cur.rowcount


def retry_dead(job_id: int | None = None) -> int:
    now = _ts(_now())
    sql = "UPDATE jobs SET state='queued', attempts=0, run_after=?, updated_at=?, finished_at=NULL WHERE state='dead'"
    params: list[Any] = [now, now]
    if job_id is not None:
        sql += " AND id=?"
        params.append(job_id)
    try:
        return db.execute(sql, params).rowcount
    except sqlite3.IntegrityError:
        return 0


def stats() -> dict[str, Any]:
    rows = db.query("SELECT kind, state, COUNT(*) n FROM jobs GROUP BY kind, state")
    out: dict[str, Any] = {"by_state": {}, "by_kind": {}}
    for r in rows:
        out["by_state"][r["state"]] = out["by_state"].get(r["state"], 0) + r["n"]
        out["by_kind"].setdefault(r["kind"], {})[r["state"]] = r["n"]
    return out


def purge_finished(older_than_days: int = 14) -> int:
    cutoff = _ts(_now() - timedelta(days=older_than_days))
    return db.execute(
        "DELETE FROM jobs WHERE state IN ('done','cancelled') AND finished_at < ?", (cutoff,)
    ).rowcount

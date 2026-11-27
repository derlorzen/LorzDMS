"""Hintergrund-Worker mit Scheduler (eigener Prozess, von s6 überwacht)."""

from __future__ import annotations

import logging
import os
import signal
import socket
import threading
import time
from datetime import datetime, timedelta, timezone

from . import appsettings, bootstrap, db, jobqueue, notify, organize
from .config import get_settings
from .google import http as ghttp
from .pipeline import processor
from .resources import can_process
from .sources import intake

log = logging.getLogger("lorzdms.worker")
_stop = threading.Event()


def handle(job: dict) -> None:
    kind, payload = job["kind"], job["payload"]
    if kind == "process_document":
        state = processor.process(int(payload["document_id"]), force_ocr=bool(payload.get("force_ocr")))
        log.info("Dokument %s: %s", payload["document_id"], state)
    elif kind == "sync_source":
        n = intake.sync_source(int(payload["source_id"]))
        log.info("Quelle %s: %d neue Dokumente", payload["source_id"], n)
    elif kind == "scan_local_inbox":
        intake.scan_local_inbox()
    elif kind == "deadline_reminders":
        n = organize.run_reminders(notify.send)
        db.set_setting("reminders_last_run", {"at": db.utcnow(), "sent": n, "status": "ok"})
        log.info("Fristen-Erinnerungen: %d gesendet", n)
    elif kind == "maintenance":
        jobqueue.purge_finished()
    else:
        raise processor.PermanentError(f"Unbekannter Job-Typ {kind}")


def run_one(worker_id: str) -> bool:
    s = get_settings()
    if db.get_setting("processing_paused", False):
        return False
    job = jobqueue.claim(worker_id, lease_seconds=s.ocr_timeout_seconds + 600)
    if job is None:
        return False
    ok, why = can_process(s, job["priority"])
    if not ok and job["kind"] == "process_document":
        jobqueue.defer(job["id"], 120, why)
        log.info("Job %s verschoben: %s", job["id"], why)
        return False
    try:
        handle(job)
    except processor.PermanentError as exc:
        jobqueue.fail(job["id"], str(exc), retryable=False)
        if job["kind"] == "process_document":
            processor.mark_failed(int(job["payload"]["document_id"]), str(exc))
    except ghttp.AuthExpired as exc:
        # nicht sinnlos wiederholen: lange warten, bis neu verbunden wurde
        jobqueue.fail(job["id"], f"Google-Anmeldung erforderlich: {exc}", retryable=True)
    except Exception as exc:  # noqa: BLE001
        log.warning("Job %s (%s) fehlgeschlagen: %s", job["id"], job["kind"], type(exc).__name__)
        status = jobqueue.fail(job["id"], f"{type(exc).__name__}: {exc}")
        if status == "dead" and job["kind"] == "process_document":
            processor.mark_failed(int(job["payload"]["document_id"]), f"{type(exc).__name__}: {exc}")
    else:
        jobqueue.complete(job["id"])
    return True


def schedule_due() -> None:
    """Fällige Quellen-Synchronisierungen einreihen."""
    now = datetime.now(timezone.utc)
    for src in db.query("SELECT * FROM sources WHERE enabled=1 AND kind IN ('gmail','drive','local')"):
        interval = src["poll_interval_seconds"] if src["kind"] != "local" else get_settings().scan_interval_seconds
        last = datetime.fromisoformat(src["last_sync_at"]) if src["last_sync_at"] else None
        if last is None or now - last >= timedelta(seconds=interval):
            if src["kind"] == "local":
                jobqueue.enqueue("scan_local_inbox", {}, priority=90, dedupe_key="scan_local")
            else:
                if src["kind"] == "gmail" and not appsettings.get("setup_completed"):
                    continue
                jobqueue.enqueue("sync_source", {"source_id": src["id"]}, priority=80, dedupe_key=f"sync:{src['id']}")


def schedule_reminders(now: datetime | None = None) -> bool:
    """Reiht höchstens alle 30 Minuten die Fristenprüfung ein (ab ``reminder_hour`` Ortszeit)."""
    if not appsettings.get("reminders_enabled"):
        return False
    local = (now or datetime.now(timezone.utc)).astimezone()
    if local.hour < int(appsettings.get("reminder_hour") or 0):
        return False
    if not notify.available():
        db.set_setting("reminders_last_run", {"at": db.utcnow(), "sent": 0, "status": "unavailable"})
        return False
    last = db.get_setting("reminders_scheduled_at")
    if last and local - datetime.fromisoformat(last) < timedelta(minutes=30):
        return False
    db.set_setting("reminders_scheduled_at", local.isoformat())
    jobqueue.enqueue("deadline_reminders", {}, priority=70, dedupe_key="deadline_reminders")
    return True


def main() -> None:
    bootstrap.init(role="worker")
    worker_id = f"{socket.gethostname()}:{os.getpid()}"
    signal.signal(signal.SIGTERM, lambda *_: _stop.set())
    signal.signal(signal.SIGINT, lambda *_: _stop.set())
    recovered = jobqueue.recover_expired()
    if recovered:
        log.info("%d unterbrochene Jobs wieder eingereiht", recovered)
    jobqueue.enqueue("maintenance", {}, priority=900, dedupe_key="maintenance")
    last_schedule = 0.0
    log.info("Worker gestartet (%s)", worker_id)
    while not _stop.is_set():
        if time.monotonic() - last_schedule > 15:
            try:
                schedule_due()
                schedule_reminders()
                jobqueue.recover_expired()
                db.set_setting("worker_heartbeat", db.utcnow())
            except Exception:  # noqa: BLE001
                log.exception("Scheduler-Fehler")
            last_schedule = time.monotonic()
        try:
            busy = run_one(worker_id)
        except Exception:  # noqa: BLE001
            log.exception("Worker-Fehler")
            busy = False
        if not busy:
            _stop.wait(2.0)
    log.info("Worker beendet")


if __name__ == "__main__":
    main()

"""Erfassung neuer Dokumente aus allen Quellen (idempotent über source_kind+source_ref)."""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
import sqlite3
import time
from pathlib import Path

from .. import db, jobqueue
from ..config import get_settings
from ..google import http as ghttp
from ..google.gmail import attachments, message_meta
from ..pipeline import states
from ..pipeline.filetypes import SUPPORTED
from ..pipeline.processor import journal, original_path
from .. import services

log = logging.getLogger("lorzdms.sources")
ALLOWED_EXT = tuple(e for exts in SUPPORTED.values() for e in exts)


def register(
    *, source_id: int | None, kind: str, ref: str, filename: str, metadata: dict | None = None,
    email_meta: dict | None = None, priority: int = 100,
) -> int | None:
    """Legt ein Dokument an und reiht die Verarbeitung ein. ``None`` = bereits bekannt."""
    now = db.utcnow()
    try:
        cur = db.execute(
            "INSERT INTO documents(source_id, source_kind, source_ref, original_filename, state, state_changed_at, metadata, email_meta, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            (source_id, kind, ref, filename[:255], states.NEW, now, json.dumps(metadata or {}, ensure_ascii=False),
             json.dumps(email_meta, ensure_ascii=False) if email_meta else None, now, now),
        )
    except sqlite3.IntegrityError:
        return None
    doc_id = cur.lastrowid
    journal(doc_id, "intake", "ok", f"Erfasst aus Quelle '{kind}'")
    jobqueue.enqueue("process_document", {"document_id": doc_id}, priority=priority, dedupe_key=f"doc:{doc_id}")
    return doc_id


def ensure_builtin_sources() -> None:
    for kind, name in (("upload", "Manueller Upload"), ("local", "Lokaler Eingang")):
        if not db.one("SELECT id FROM sources WHERE kind=?", (kind,)):
            db.execute(
                "INSERT INTO sources(kind, name, config, poll_interval_seconds, created_at) VALUES (?,?,?,?,?)",
                (kind, name, "{}", get_settings().scan_interval_seconds, db.utcnow()),
            )


def source_id(kind: str) -> int | None:
    row = db.one("SELECT id FROM sources WHERE kind=? ORDER BY id LIMIT 1", (kind,))
    return row["id"] if row else None


# Upload -----------------------------------------------------------------------

def register_upload(data: bytes, filename: str, user_id: int | None) -> tuple[int | None, str]:
    sha = hashlib.sha256(data).hexdigest()
    ref = f"upload:{sha}"
    existing = db.one("SELECT id FROM documents WHERE source_kind='upload' AND source_ref=?", (ref,))
    if existing:
        return existing["id"], "duplicate"
    doc_id = register(source_id=source_id("upload"), kind="upload", ref=ref, filename=filename,
                      metadata={"uploaded_by": user_id})
    if doc_id is None:
        return None, "duplicate"
    dest = original_path(doc_id)
    tmp = dest.with_suffix(".part")
    tmp.write_bytes(data)
    tmp.replace(dest)
    return doc_id, "created"


# Lokaler Eingang -------------------------------------------------------------

_seen: dict[str, tuple[int, float]] = {}


def scan_local_inbox() -> int:
    s = get_settings()
    if not s.local_inbox_enabled or not s.inbox_dir.is_dir():
        return 0
    sid = source_id("local")
    created = 0
    now = time.time()
    for path in sorted(s.inbox_dir.rglob("*")):
        if not path.is_file() or path.name.startswith(".") or path.suffix.lower() not in ALLOWED_EXT:
            continue
        st = path.stat()
        key = str(path)
        prev = _seen.get(key)
        _seen[key] = (st.st_size, st.st_mtime)
        # Datei gilt als vollständig, wenn Größe/Zeit bei zwei Scans gleich und >10 s alt
        if prev != (st.st_size, st.st_mtime) or now - st.st_mtime < 10:
            continue
        ref = f"{path.relative_to(s.inbox_dir)}|{st.st_size}|{int(st.st_mtime)}"
        doc_id = register(source_id=sid, kind="local", ref=ref, filename=path.name, metadata={"source_path": str(path)})
        if doc_id:
            created += 1
    db.execute("UPDATE sources SET last_sync_at=?, last_status='ok', last_error=NULL WHERE id=?", (db.utcnow(), sid))
    return created


# Gmail ------------------------------------------------------------------------

def sync_gmail(source: dict) -> int:
    """Liest neue Nachrichten (nur lesend). Erstlauf: Suche; danach History-API."""
    cfg = json.loads(source["config"] or "{}")
    client = services.gmail(source["account_id"])
    query = cfg.get("query") or "has:attachment filename:pdf newer_than:14d"
    label_ids = cfg.get("label_ids") or None
    extensions = tuple(cfg.get("extensions") or (".pdf",))
    cursor = source.get("cursor")
    message_ids: list[str]
    new_cursor = cursor
    if cursor:
        try:
            message_ids, new_cursor = client.history(cursor, label_ids[0] if label_ids else None)
        except ghttp.GoogleApiError as exc:
            if exc.status != 404:
                raise
            log.warning("Gmail-History zu alt – Vollabgleich")
            message_ids = list(client.search(query, label_ids))
            new_cursor = client.profile()["historyId"]
    else:
        new_cursor = client.profile()["historyId"]
        message_ids = list(client.search(query, label_ids, limit=int(cfg.get("backfill_limit", 200))))
    created = 0
    for mid in message_ids:
        try:
            msg = client.message(mid)
        except ghttp.GoogleApiError as exc:
            # In der History gemeldete, inzwischen gelöschte Nachrichten (z. B. Entwürfe, Spam)
            # überspringen, statt den ganzen Abgleich dauerhaft zu blockieren.
            if exc.status == 404:
                log.info("Gmail-Nachricht nicht mehr vorhanden – übersprungen")
                continue
            raise
        if label_ids and not set(label_ids) & set(msg.get("labelIds", [])):
            continue
        meta = message_meta(msg)
        for att in attachments(msg, extensions):
            doc_id = register(
                source_id=source["id"], kind="gmail", ref=f"{mid}:{att['part_id']}", filename=att["filename"],
                metadata={"gmail_part": att}, email_meta=meta,
            )
            if doc_id:
                created += 1
    db.execute("UPDATE sources SET cursor=? WHERE id=?", (new_cursor, source["id"]))
    return created


# Google Drive -----------------------------------------------------------------

def sync_drive(source: dict) -> int:
    """Überwacht Eingangsordner (Listing; Changes-API folgt). Liest nur."""
    cfg = json.loads(source["config"] or "{}")
    client = services.drive(source["account_id"])
    folders = list(cfg.get("folder_ids") or [])
    if cfg.get("recursive"):
        queue, seen = list(folders), set(folders)
        while queue:
            fid = queue.pop()
            for sub in client.children(fid, folders_only=True):
                if sub["id"] not in seen:
                    seen.add(sub["id"])
                    folders.append(sub["id"])
                    queue.append(sub["id"])
    created = 0
    for fid in folders:
        for f in client.files_in(fid):
            if not f["name"].lower().endswith(ALLOWED_EXT):
                continue
            existing = db.one("SELECT id FROM documents WHERE source_kind='drive' AND source_ref=?", (f["id"],))
            if existing:
                continue
            # Datei ggf. von einer anderen Quelle bereits erfasst (gleiche Prüfsumme)?
            doc_id = register(
                source_id=source["id"], kind="drive", ref=f["id"], filename=f["name"],
                metadata={"drive_md5": f.get("md5Checksum"), "drive_parent": fid},
            )
            if doc_id:
                created += 1
    return created


def sync_source(source_id_: int) -> int:
    row = db.one("SELECT * FROM sources WHERE id=?", (source_id_,))
    if row is None or not row["enabled"]:
        return 0
    source = dict(row)
    try:
        if source["kind"] == "gmail":
            n = sync_gmail(source)
        elif source["kind"] == "drive":
            n = sync_drive(source)
        elif source["kind"] == "local":
            n = scan_local_inbox()
        else:
            n = 0
    except ghttp.AuthExpired as exc:
        db.execute("UPDATE sources SET last_sync_at=?, last_status='auth_error', last_error=? WHERE id=?",
                   (db.utcnow(), "Google-Anmeldung abgelaufen – bitte neu verbinden", source_id_))
        raise exc
    except Exception as exc:
        db.execute("UPDATE sources SET last_sync_at=?, last_status='error', last_error=? WHERE id=?",
                   (db.utcnow(), f"{type(exc).__name__}: {str(exc)[:300]}", source_id_))
        raise
    db.execute("UPDATE sources SET last_sync_at=?, last_status='ok', last_error=NULL WHERE id=?", (db.utcnow(), source_id_))
    return n


def copy_into_workdir(src: Path, doc_id: int) -> None:
    dest = original_path(doc_id)
    shutil.copy2(src, dest)

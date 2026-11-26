"""Benutzeraktionen auf Dokumenten (Prüfung, Korrektur, Rückgängig)."""

from __future__ import annotations

import json
from typing import Any

from . import db, jobqueue, services
from .pipeline import naming, processor, states
from .pipeline.processor import journal, load, set_state, update

EDITABLE = {"document_type", "sender", "document_date", "title", "tags", "reference", "person"}


class ActionError(ValueError):
    pass


def _enqueue(doc_id: int, **payload: Any) -> None:
    jobqueue.enqueue("process_document", {"document_id": doc_id, **payload}, priority=50, dedupe_key=f"doc:{doc_id}")


def approve(doc_id: int, user_id: int, *, folder_drive_id: str | None = None, filename: str | None = None,
            corrections: dict | None = None) -> dict:
    doc = load(doc_id)
    if doc["state"] not in (states.NEEDS_REVIEW, states.OBSERVED, states.ANALYZED):
        raise ActionError(f"Dokument ist im Zustand '{doc['state']}' und kann nicht freigegeben werden")
    from . import appsettings

    if appsettings.get("processing_mode") == "observe":
        raise ActionError("Beobachtungsmodus aktiv: Ablage in Drive ist deaktiviert")
    folder = folder_drive_id or doc["target_folder_drive_id"]
    if not folder or services.folder_account(folder) is None:
        raise ActionError("Bitte einen freigegebenen Zielordner wählen")
    meta = dict(doc["metadata"])
    changes = {}
    for k, v in (corrections or {}).items():
        if k not in EDITABLE:
            raise ActionError(f"Feld '{k}' kann nicht bearbeitet werden")
        if meta.get(k) != v:
            changes[k] = {"from": meta.get(k), "to": v}
        meta[k] = v
    if folder != doc["target_folder_drive_id"]:
        changes["folder"] = {"from": doc["target_folder_drive_id"], "to": folder}
    name = doc["target_name"]
    if filename:
        ext = "." + name.rsplit(".", 1)[-1] if name and "." in name else ".pdf"
        name = naming.render("{title}", {"title": filename.rsplit(".", 1)[0]}, doc["original_filename"], ext)
        changes["filename"] = {"from": doc["target_name"], "to": name}
    elif corrections:
        name = naming.render((doc.get("decision") or {}).get("template") or appsettings.get("filename_template"),
                             meta, doc["original_filename"], "." + (doc["target_name"] or "x.pdf").rsplit(".", 1)[-1])
    decision = dict(doc.get("decision") or {})
    decision["approved_by"] = user_id
    decision["corrections"] = changes
    update(doc, metadata=meta, target_folder_drive_id=folder, target_name=name, decision=decision,
           document_type=meta.get("document_type"), sender=meta.get("sender"), document_date=meta.get("document_date"),
           title=meta.get("title"), tags=meta.get("tags", doc["tags"]))
    if changes:
        # Korrekturen werden als Lernbeispiel gespeichert, ändern aber keine globalen Regeln.
        journal(doc_id, "review", "info", "Korrektur gespeichert", changes=changes, user=user_id)
    set_state(doc, states.APPROVED)
    journal(doc_id, "review", "ok", "Ablage freigegeben", user=user_id)
    db.audit("document.approve", user_id, f"document:{doc_id}", folder=folder)
    _enqueue(doc_id)
    return load(doc_id)


def skip(doc_id: int, user_id: int) -> None:
    doc = load(doc_id)
    set_state(doc, states.EXCLUDED)
    journal(doc_id, "review", "info", "Verarbeitung übersprungen", user=user_id)
    db.audit("document.skip", user_id, f"document:{doc_id}")


def _resume_state(doc: dict, *, force_ocr: bool = False) -> str:
    """Zustand, ab dem ein Dokument erneut verarbeitet wird (nichts überspringen, was fehlt)."""
    doc_id = doc["id"]
    if not processor.original_path(doc_id).exists():
        if doc["source_kind"] == "upload":
            raise ActionError("Arbeitskopie des Uploads fehlt; bitte erneut hochladen")
        return states.NEW  # Datei neu aus der Quelle abrufen
    if doc.get("sha256") is None:
        return states.FETCHED
    has_text = db.one("SELECT 1 FROM document_text WHERE document_id=?", (doc_id,)) is not None
    if force_ocr or not has_text:
        return states.VALIDATED
    return states.EXTRACTED


def retry_failed_jobs(user_id: int | None) -> int:
    """Endgültig fehlgeschlagene Jobs neu einreihen und alle Dokumente im Zustand 'failed'
    ab dem passenden Schritt erneut verarbeiten. Rückgabe: Anzahl neu eingereihter Arbeiten."""
    n = jobqueue.retry_dead()
    for row in db.query("SELECT id FROM documents WHERE state=?", (states.FAILED,)):
        doc = load(row["id"])
        try:
            target = _resume_state(doc)
        except ActionError:
            continue
        db.execute("UPDATE documents SET state=?, state_changed_at=?, error=NULL WHERE id=?", (target, db.utcnow(), doc["id"]))
        journal(doc["id"], "retry", "info", "Erneuter Versuch nach endgültigem Fehler", user=user_id)
        if jobqueue.enqueue("process_document", {"document_id": doc["id"]}, priority=50, dedupe_key=f"doc:{doc['id']}") is not None:
            n += 1
    db.audit("jobs.retry_dead", user_id, None, count=n)
    return n


def reanalyze(doc_id: int, user_id: int, *, force_ocr: bool = False) -> None:
    doc = load(doc_id)
    if doc["state"] not in (states.NEEDS_REVIEW, states.OBSERVED, states.EXCLUDED, states.DUPLICATE, states.FAILED):
        raise ActionError(f"Erneute Analyse im Zustand '{doc['state']}' nicht möglich")
    target = _resume_state(doc, force_ocr=force_ocr)
    db.execute("UPDATE documents SET state=?, state_changed_at=?, error=NULL WHERE id=?", (target, db.utcnow(), doc_id))
    journal(doc_id, "review", "info", "Erneute Analyse angefordert", user=user_id, force_ocr=force_ocr)
    _enqueue(doc_id, force_ocr=force_ocr)


def undo(doc_id: int, user_id: int) -> dict:
    doc = load(doc_id)
    if doc["state"] != states.DONE:
        raise ActionError("Nur abgeschlossene Ablagen können rückgängig gemacht werden")
    op = db.one("SELECT * FROM drive_operations WHERE document_id=? AND status='done' AND kind IN ('move','upload') ORDER BY id DESC LIMIT 1", (doc_id,))
    if op is None:
        raise ActionError("Keine Drive-Operation gefunden")
    account = services.folder_account(op["to_parent"])
    if account is None:
        raise ActionError("Zielordner ist nicht mehr freigegeben")
    guard = services.guard(account)
    if op["kind"] == "move":
        parents = json.loads(op["from_parents"] or "[]")
        if not parents:
            raise ActionError("Ursprungsordner unbekannt")
        guard.restore(op["drive_file_id"], parents, op["old_name"])
        to_parent, new_name = ",".join(parents), op["old_name"]
    else:
        review = services.review_folder(account)
        if not review:
            raise ActionError("Für hochgeladene Dateien wird ein Prüfordner benötigt (Rolle 'review')")
        guard.move(op["drive_file_id"], review, None)
        to_parent, new_name = review, op["new_name"]
    db.execute("UPDATE drive_operations SET status='undone', finished_at=? WHERE id=?", (db.utcnow(), op["id"]))
    db.execute(
        "INSERT INTO drive_operations(document_id, kind, drive_file_id, from_parents, to_parent, old_name, new_name, status, created_at, finished_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?)",
        (doc_id, "undo", op["drive_file_id"], json.dumps([op["to_parent"]]), to_parent, op["new_name"], new_name, "done", db.utcnow(), db.utcnow()),
    )
    journal(doc_id, "undo", "ok", "Ablage rückgängig gemacht", user=user_id)
    db.audit("document.undo", user_id, f"document:{doc_id}")
    set_state(doc, states.NEEDS_REVIEW, drive_file_id=op["drive_file_id"] if op["kind"] == "move" else doc["drive_file_id"])
    return load(doc_id)

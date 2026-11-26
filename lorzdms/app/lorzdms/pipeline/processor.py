"""Verarbeitungspipeline eines Dokuments.

``process(doc_id)`` führt alle offenen Schritte ab dem aktuellen Zustand aus. Jeder
Schritt ist idempotent und wird im Journal protokolliert. Ausnahmen führen zu einem
Job-Retry; der Zustand bleibt auf dem letzten erfolgreichen Schritt stehen, sodass nach
einem Neustart exakt dort fortgesetzt wird.

Datensicherheit:
- Quellen (Gmail, Drive-Eingang, lokale Dateien) werden vor der verifizierten Ablage nie
  verändert. Gmail wird nie verändert.
- Vor jeder Drive-Schreiboperation wird ein ``pending``-Eintrag in ``drive_operations``
  geschrieben; ein Wiederanlauf prüft zuerst, ob die Operation bereits ausgeführt wurde.
- Temporäre Dateien werden erst im Zustand ``verified`` entfernt.
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
from pathlib import Path
from typing import Any

from .. import appsettings, db, services
from ..ai import providers as ai_providers
from ..config import get_settings
from ..crypto import get_secret
from . import filetypes, naming, rules, states, nvidia_ocr, text as textmod

log = logging.getLogger("lorzdms.pipeline")


class PermanentError(RuntimeError):
    """Fehler, bei dem ein erneuter Versuch nicht hilft."""


# Hilfsfunktionen --------------------------------------------------------------

def journal(doc_id: int | None, step: str, status: str, message: str, **data: Any) -> None:
    db.execute(
        "INSERT INTO journal(document_id, ts, step, status, message, data) VALUES (?,?,?,?,?,?)",
        (doc_id, db.utcnow(), step, status, message[:1000], json.dumps(data, ensure_ascii=False) if data else None),
    )


def load(doc_id: int) -> dict:
    row = db.one(
        "SELECT d.*, s.name AS source_name, s.account_id AS source_account_id, s.config AS source_config "
        "FROM documents d LEFT JOIN sources s ON s.id=d.source_id WHERE d.id=?",
        (doc_id,),
    )
    if row is None:
        raise PermanentError(f"Dokument {doc_id} existiert nicht")
    d = db.row_to_dict(row, ("tags", "metadata", "email_meta", "decision", "source_config"))
    d["tags"] = d.get("tags") or []
    d["metadata"] = d.get("metadata") or {}
    return d


def set_state(doc: dict, new: str, **fields: Any) -> None:
    states.check(doc["state"], new)
    fields["state"] = new
    fields["state_changed_at"] = db.utcnow()
    fields["updated_at"] = fields["state_changed_at"]
    cols = ", ".join(f"{k}=?" for k in fields)
    vals = [json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v for v in fields.values()]
    db.execute(f"UPDATE documents SET {cols} WHERE id=?", (*vals, doc["id"]))
    doc.update(fields)


def update(doc: dict, **fields: Any) -> None:
    fields["updated_at"] = db.utcnow()
    cols = ", ".join(f"{k}=?" for k in fields)
    vals = [json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v for v in fields.values()]
    db.execute(f"UPDATE documents SET {cols} WHERE id=?", (*vals, doc["id"]))
    doc.update(fields)


def workdir(doc_id: int) -> Path:
    p = get_settings().temp_dir / f"doc-{doc_id}"
    p.mkdir(parents=True, exist_ok=True)
    return p


def original_path(doc_id: int) -> Path:
    return workdir(doc_id) / "original"


def file_hashes(path: Path) -> tuple[str, str]:
    sha, md5 = hashlib.sha256(), hashlib.md5()  # noqa: S324 – MD5 nur zum Abgleich mit Drive
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            sha.update(chunk)
            md5.update(chunk)
    return sha.hexdigest(), md5.hexdigest()


def get_text(doc_id: int) -> str:
    row = db.one("SELECT text FROM document_text WHERE document_id=?", (doc_id,))
    return row["text"] if row else ""


# Schritte ---------------------------------------------------------------------

def step_fetch(doc: dict) -> None:
    dest = original_path(doc["id"])
    s = get_settings()
    max_bytes = s.max_file_size_mb * 1024 * 1024
    if dest.exists() and dest.stat().st_size > 0:
        set_state(doc, states.FETCHED)
        return
    kind = doc["source_kind"]
    meta = doc["metadata"]
    if kind == "drive":
        account = doc["source_account_id"]
        info = services.drive(account).get(doc["source_ref"])
        if info.get("trashed"):
            raise PermanentError("Datei liegt im Drive-Papierkorb")
        size, md5 = services.drive(account).download(doc["source_ref"], dest, max_bytes)
        if info.get("md5Checksum") and info["md5Checksum"] != md5:
            dest.unlink(missing_ok=True)
            raise RuntimeError("MD5 des Downloads stimmt nicht mit Drive überein")
    elif kind == "gmail":
        account = doc["source_account_id"]
        client = services.gmail(account)
        message_id, part_id = doc["source_ref"].split(":", 1)
        msg = client.message(message_id)
        from ..google.gmail import attachments

        match = [a for a in attachments(msg, extensions=(".pdf", ".jpg", ".jpeg", ".png", ".tif", ".tiff")) if a["part_id"] == part_id]
        if not match:
            raise PermanentError("Anhang in der Nachricht nicht mehr gefunden")
        if match[0]["size"] > max_bytes:
            raise PermanentError("Anhang überschreitet das Größenlimit")
        data = client.attachment(message_id, match[0]["attachment_id"])
        tmp = dest.with_suffix(".part")
        tmp.write_bytes(data)
        tmp.replace(dest)
    elif kind in ("local", "upload"):
        src = meta.get("source_path")
        if kind == "local" and src and Path(src).exists():
            shutil.copy2(src, dest)
        else:
            raise PermanentError("Lokale Quelldatei fehlt")
    else:
        raise PermanentError(f"Unbekannte Quelle {kind}")
    journal(doc["id"], "fetch", "ok", "Datei erfasst", bytes=dest.stat().st_size)
    set_state(doc, states.FETCHED)


def step_validate(doc: dict) -> None:
    s = get_settings()
    path = original_path(doc["id"])
    v = filetypes.validate(path, doc["original_filename"], s.max_file_size_mb * 1024 * 1024, s.max_image_pixels)
    if not v.ok:
        if v.quarantine:
            qdir = s.quarantine_dir / f"doc-{doc['id']}"
            qdir.mkdir(parents=True, exist_ok=True)
            shutil.move(str(path), qdir / "original")
            journal(doc["id"], "validate", "error", f"Quarantäne: {v.reason}")
            set_state(doc, states.QUARANTINED, error=v.reason, mime_type=v.mime)
        else:
            journal(doc["id"], "validate", "error", v.reason)
            set_state(doc, states.FAILED, error=v.reason, mime_type=v.mime)
        return
    sha, md5 = file_hashes(path)
    signed = v.mime == "application/pdf" and filetypes.pdf_is_signed(path)
    update(doc, mime_type=v.mime, sha256=sha, md5=md5, size_bytes=path.stat().st_size, signed_pdf=int(signed))
    dup = db.one(
        "SELECT id FROM documents WHERE sha256=? AND id<>? AND state NOT IN ('failed','quarantined','duplicate') ORDER BY id LIMIT 1",
        (sha, doc["id"]),
    )
    journal(doc["id"], "validate", "ok", "Typ und Größe geprüft", mime=v.mime, signed=signed)
    if dup:
        journal(doc["id"], "dedupe", "info", f"Identisch mit Dokument {dup['id']}")
        set_state(doc, states.DUPLICATE, duplicate_of=dup["id"])
        return
    set_state(doc, states.VALIDATED)


def extract_document_text(path: Path, mime: str, work: Path, *, timeout: int, force_ocr: bool = False) -> textmod.TextResult:
    provider = appsettings.get("ocr_provider") or {}
    if provider.get("kind") == "nvidia_nemotron_ocr_v2":
        result = nvidia_ocr.extract(path, mime, timeout=timeout, force_ocr=force_ocr)
        # Prevent reuse of a stale derivative from an earlier local OCR attempt.
        (work / "ocr.pdf").unlink(missing_ok=True)
        if appsettings.get("original_strategy") == "derivative_only":
            result.warnings.append("NVIDIA OCR erzeugt kein OCR-PDF; Original wird abgelegt")
        return result
    return textmod.extract(path, mime, work, languages=get_settings().ocr_languages,
                           timeout=timeout, force_ocr=force_ocr)


def step_extract(doc: dict, force_ocr: bool = False) -> None:
    s = get_settings()
    path = original_path(doc["id"])
    if not path.exists():
        raise RuntimeError("Arbeitskopie fehlt – erneuter Abruf nötig")
    res = extract_document_text(
        path, doc["mime_type"], workdir(doc["id"]),
        timeout=s.ocr_timeout_seconds, force_ocr=force_ocr,
    )
    text_hash = hashlib.sha256(" ".join(res.text.split()).lower().encode()).hexdigest() if res.text.strip() else None
    db.execute(
        "INSERT INTO document_text(document_id, text, pages, method) VALUES (?,?,?,?) "
        "ON CONFLICT(document_id) DO UPDATE SET text=excluded.text, pages=excluded.pages, method=excluded.method",
        (doc["id"], res.text, json.dumps(res.pages, ensure_ascii=False), res.method),
    )
    for w in res.warnings:
        journal(doc["id"], "extract", "warn", w)
    journal(
        doc["id"], "extract", "ok", f"Text extrahiert ({res.method})",
        pages=res.page_count, chars=len(res.text), ocr=res.ocr_used, seconds=res.ocr_seconds,
    )
    similar = None
    if text_hash:
        similar = db.one(
            "SELECT id FROM documents WHERE text_sha256=? AND id<>? AND state NOT IN ('failed','duplicate') LIMIT 1",
            (text_hash, doc["id"]),
        )
    meta = dict(doc["metadata"])
    if similar:
        meta["possible_duplicate_of"] = similar["id"]
        journal(doc["id"], "dedupe", "warn", f"Gleicher Textinhalt wie Dokument {similar['id']} (anderer Scan?)")
    set_state(
        doc, states.EXTRACTED, text_sha256=text_hash, page_count=res.page_count,
        ocr_used=int(res.ocr_used), ocr_seconds=res.ocr_seconds, metadata=meta,
    )


def _provider_config() -> ai_providers.ProviderConfig | None:
    p = appsettings.get("ai_provider")
    if not p or not p.get("kind") or p.get("kind") == "none":
        return None
    key = get_secret("ai_api_key") if p.get("has_key") else None
    return ai_providers.ProviderConfig(kind=p["kind"], base_url=p["base_url"], model=p["model"], api_key=key)


def _calibrate(ai_conf: float, folder_ok: bool, meta: dict) -> float:
    essentials = [meta.get("document_date"), meta.get("sender"), meta.get("document_type")]
    completeness = sum(1 for e in essentials if e) / len(essentials)
    score = 0.6 * ai_conf + 0.2 * (1.0 if folder_ok else 0.0) + 0.2 * completeness
    return round(min(score, float(appsettings.get("ai_confidence_cap"))), 3)


def step_analyze(doc: dict) -> None:
    text = get_text(doc["id"])
    ctx = rules.build_context(doc, text)
    outcome = rules.apply_rules(rules.load_rules(), ctx)
    a = outcome.actions
    reasons: list[str] = []
    decision: dict[str, Any] = {"rules": outcome.matched, "conflicts": outcome.conflicts, "ai": None}
    meta = dict(doc["metadata"])
    if a.get("exclude"):
        journal(doc["id"], "analyze", "info", "Per Regel ausgeschlossen", rules=outcome.matched)
        set_state(doc, states.EXCLUDED, decision=decision)
        return
    folder = a.get("folder_drive_id")
    confidence = 1.0 if folder else 0.0
    ai_result = None
    cfg = _provider_config()
    folders = services.archive_folders()
    if cfg is not None and text.strip():
        try:
            email = doc.get("email_meta") or {}
            call = ai_providers.analyze(
                cfg, text, folders,
                {"dateiname": doc["original_filename"], "betreff": email.get("subject"), "absender": email.get("from_email")},
                allow_external=bool(appsettings.get("allow_external_ai")),
            )
            ai_result = call.result
            decision["ai"] = {
                "provider": call.provider, "model": call.model, "seconds": round(call.seconds, 2),
                "input_tokens": call.input_tokens, "output_tokens": call.output_tokens,
                "self_confidence": ai_result.confidence, "reasoning": ai_result.reasoning,
                "uncertainties": ai_result.uncertainties, "alternatives": ai_result.alternative_folder_ids,
            }
            journal(doc["id"], "analyze", "ok", "KI-Analyse abgeschlossen", provider=call.provider, model=call.model,
                    tokens_in=call.input_tokens, tokens_out=call.output_tokens)
        except ai_providers.ExternalNotAllowed as exc:
            reasons.append(str(exc))
            journal(doc["id"], "analyze", "warn", str(exc))
        except ai_providers.ProviderError as exc:
            reasons.append(f"KI nicht verfügbar: {exc}")
            journal(doc["id"], "analyze", "warn", f"KI-Fehler: {exc}")
    if ai_result is not None:
        ai_meta = ai_result.model_dump(exclude={"confidence", "reasoning", "uncertainties", "alternative_folder_ids", "suggested_folder_id"})
        for k, v in ai_meta.items():
            if v not in (None, [], ""):
                meta[k] = v
        meta["reference"] = ai_result.invoice_number or ai_result.case_number or ai_result.contract_number or ai_result.customer_number
        if not folder and ai_result.suggested_folder_id:
            folder = ai_result.suggested_folder_id
            confidence = _calibrate(ai_result.confidence, True, meta)
        if ai_result.confidentiality == "highly_sensitive" and appsettings.get("review_sensitive"):
            reasons.append("Als hochsensibel eingestuft")
    for key in ("document_type", "sender"):
        if a.get(key):
            meta[key] = a[key]
    if not folder:
        reasons.append("Kein Ablageordner ermittelt (keine passende Regel" + (" und kein KI-Vorschlag)" if cfg else ", keine KI konfiguriert)"))
    if outcome.conflicts:
        reasons += outcome.conflicts
    if a.get("review"):
        reasons.append("Regel verlangt Prüfung")
    if folder and services.folder_account(folder) is None:
        reasons.append("Zielordner ist nicht freigegeben")
        folder = None
    template = a.get("filename_template") or appsettings.get("filename_template")
    ext = Path(doc["original_filename"]).suffix or {"application/pdf": ".pdf"}.get(doc["mime_type"], "")
    if doc["mime_type"] and doc["mime_type"].startswith("image/") and appsettings.get("original_strategy") != "original_only":
        ext = ".pdf"
    target_name = naming.render(template, meta, doc["original_filename"], ext or ".pdf")
    tags = list(dict.fromkeys((doc["tags"] or []) + a.get("tags", []) + (ai_result.tags if ai_result else [])))
    decision.update({"folder_drive_id": folder, "confidence": confidence, "review_reasons": reasons, "template": template})
    visibility = a.get("visibility") or ("admins" if ai_result and ai_result.confidentiality == "highly_sensitive" else doc.get("visibility", "members"))
    update(
        doc, metadata=meta, tags=tags, decision=decision, confidence=confidence, target_folder_drive_id=folder,
        target_name=target_name, document_type=meta.get("document_type"), sender=meta.get("sender"),
        document_date=meta.get("document_date"), title=meta.get("title") or doc.get("title"), visibility=visibility,
    )
    set_state(doc, states.ANALYZED)
    journal(doc["id"], "analyze", "ok", "Entscheidung gespeichert", folder=folder, confidence=confidence,
            rules=[m["name"] for m in outcome.matched], reasons=reasons)
    route(doc)


def route(doc: dict) -> None:
    """Entscheidet anhand Modus und Konfidenz, ob abgelegt, vorgeschlagen oder beobachtet wird."""
    mode = appsettings.get("processing_mode")
    reasons = (doc.get("decision") or {}).get("review_reasons") or []
    conf = doc.get("confidence") or 0.0
    if mode == "observe":
        journal(doc["id"], "route", "info", "Beobachtungsmodus: keine Änderung in Google Drive")
        set_state(doc, states.OBSERVED)
        return
    if mode == "auto" and appsettings.get("test_run_ok") and not reasons and doc.get("target_folder_drive_id") \
            and conf >= float(appsettings.get("auto_threshold")):
        journal(doc["id"], "route", "ok", "Automatische Ablage freigegeben", confidence=conf)
        set_state(doc, states.APPROVED)
        return
    level = "Vorschlag zur Bestätigung" if conf >= float(appsettings.get("suggest_threshold")) else "Manuelle Prüfung erforderlich"
    journal(doc["id"], "route", "info", level, confidence=conf, reasons=reasons)
    set_state(doc, states.NEEDS_REVIEW)


def _archive_account(doc: dict) -> int:
    acc = services.folder_account(doc["target_folder_drive_id"])
    if acc is None:
        raise PermanentError("Zielordner ist nicht freigegeben")
    return acc


def step_archive(doc: dict) -> None:
    target = doc["target_folder_drive_id"]
    if not target:
        set_state(doc, states.NEEDS_REVIEW)
        return
    account = _archive_account(doc)
    guard = services.guard(account)
    pending = db.one(
        "SELECT * FROM drive_operations WHERE document_id=? AND status='pending' ORDER BY id DESC LIMIT 1", (doc["id"],)
    )
    is_move = doc["source_kind"] == "drive" and doc["source_account_id"] == account
    if pending is None:
        guard.assert_writable(target)
        existing = guard.client.names_in(target)
        name = naming.resolve_conflict(doc["target_name"], existing)
        from_parents, old_name = None, None
        if is_move:
            # Ursprungsort VOR dem Verschieben festhalten (Rückgängig auch nach Absturz)
            src_meta = guard.client.get(doc["source_ref"], "id,name,parents")
            from_parents, old_name = json.dumps(src_meta.get("parents") or []), src_meta["name"]
        cur = db.execute(
            "INSERT INTO drive_operations(document_id, kind, drive_file_id, from_parents, to_parent, old_name, new_name, status, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (doc["id"], "move" if is_move else "upload", doc["source_ref"] if is_move else None, from_parents, target,
             old_name, name, "pending", db.utcnow()),
        )
        op_id = cur.lastrowid
        pending = db.one("SELECT * FROM drive_operations WHERE id=?", (op_id,))
        if doc["state"] != states.ARCHIVING:
            set_state(doc, states.ARCHIVING, target_name=name)
    else:
        op_id, name = pending["id"], pending["new_name"]
        if doc["state"] != states.ARCHIVING:
            set_state(doc, states.ARCHIVING)
    try:
        if is_move:
            current = guard.client.get(doc["source_ref"], "id,parents,name,webViewLink")
            if target in (current.get("parents") or []) and current["name"] == name:
                result = current  # bereits verschoben (Wiederanlauf)
                journal(doc["id"], "archive", "info", "Verschiebung war bereits erfolgt (Wiederanlauf)")
            else:
                result, _, _ = guard.move(doc["source_ref"], target, name)
        else:
            found = guard.client.find_by_app_property(target, "lorzdms_doc", str(doc["id"]))
            if found:
                result = found
                journal(doc["id"], "archive", "info", "Upload war bereits erfolgt (Wiederanlauf)")
            else:
                src = _archive_file(doc)
                result = guard.upload(src, name, target, _upload_mime(doc, src),
                                      {"lorzdms_doc": str(doc["id"]), "lorzdms_sha256": doc["sha256"] or ""})
    except Exception as exc:
        db.execute("UPDATE drive_operations SET error=? WHERE id=?", (str(exc)[:500], op_id))
        raise
    db.execute("UPDATE drive_operations SET status='done', drive_file_id=?, finished_at=? WHERE id=?",
               (result["id"], db.utcnow(), op_id))
    journal(doc["id"], "archive", "ok", "In Google Drive abgelegt" if not is_move else "In Google Drive verschoben",
            drive_file_id=result["id"], name=name)
    set_state(doc, states.ARCHIVED, drive_file_id=result["id"], drive_web_link=result.get("webViewLink"),
              target_name=name, archived_at=db.utcnow())


def _archive_file(doc: dict) -> Path:
    strategy = appsettings.get("original_strategy")
    deriv = workdir(doc["id"]) / "ocr.pdf"
    if strategy == "derivative_only" and deriv.exists() and not doc["signed_pdf"]:
        return deriv
    return original_path(doc["id"])


def _upload_mime(doc: dict, path: Path) -> str:
    return "application/pdf" if path.name == "ocr.pdf" else (doc["mime_type"] or "application/octet-stream")


def step_verify(doc: dict) -> None:
    account = _archive_account(doc)
    info = services.drive(account).get(doc["drive_file_id"])
    problems = []
    if info.get("trashed"):
        problems.append("Datei liegt im Papierkorb")
    if doc["target_folder_drive_id"] not in (info.get("parents") or []):
        problems.append("Datei liegt nicht im Zielordner")
    op = db.one("SELECT kind FROM drive_operations WHERE document_id=? AND status='done' ORDER BY id DESC LIMIT 1", (doc["id"],))
    uploaded_file = _archive_file(doc)
    expected_md5 = doc["md5"] if uploaded_file.name == "original" or (op and op["kind"] == "move") else file_hashes(uploaded_file)[1]
    if info.get("md5Checksum") and info["md5Checksum"] != expected_md5:
        problems.append("Prüfsumme in Drive weicht ab")
    if problems:
        journal(doc["id"], "verify", "error", "; ".join(problems))
        set_state(doc, states.ARCHIVING)  # erneuter Versuch beim nächsten Lauf
        raise RuntimeError("Verifikation fehlgeschlagen: " + "; ".join(problems))
    journal(doc["id"], "verify", "ok", "Ablage verifiziert (Ordner, Prüfsumme)")
    set_state(doc, states.VERIFIED, drive_web_link=info.get("webViewLink") or doc.get("drive_web_link"))


def index(doc: dict) -> None:
    text = get_text(doc["id"])
    db.execute("DELETE FROM documents_fts WHERE rowid=?", (doc["id"],))
    db.execute(
        "INSERT INTO documents_fts(rowid, title, filename, sender, document_type, body) VALUES (?,?,?,?,?,?)",
        (doc["id"], doc.get("title") or "", f"{doc['original_filename']} {doc.get('target_name') or ''}",
         doc.get("sender") or "", doc.get("document_type") or "", text),
    )


def cleanup(doc: dict) -> None:
    s = get_settings()
    if doc["source_kind"] == "local" and s.local_inbox_after_success == "move":
        src = Path(doc["metadata"].get("source_path", ""))
        if src.exists():
            s.processed_dir.mkdir(parents=True, exist_ok=True)
            dest = s.processed_dir / src.name
            if dest.exists():
                dest = s.processed_dir / f"{doc['id']}_{src.name}"
            shutil.move(str(src), dest)
            journal(doc["id"], "cleanup", "info", "Quelldatei nach 'processed' verschoben")
    wd = s.temp_dir / f"doc-{doc['id']}"
    if wd.exists():
        shutil.rmtree(wd, ignore_errors=True)
    journal(doc["id"], "cleanup", "ok", "Temporäre Dateien entfernt")


def step_finish(doc: dict) -> None:
    index(doc)
    cleanup(doc)
    set_state(doc, states.DONE)
    journal(doc["id"], "done", "ok", "Verarbeitung abgeschlossen")


# Orchestrierung ---------------------------------------------------------------

def process(doc_id: int, *, force_ocr: bool = False) -> str:
    doc = load(doc_id)
    for _ in range(20):
        st = doc["state"]
        if st == states.NEW:
            step_fetch(doc)
        elif st == states.FETCHED:
            step_validate(doc)
        elif st == states.VALIDATED:
            step_extract(doc, force_ocr=force_ocr)
        elif st == states.EXTRACTED:
            index(doc)  # sofort durchsuchbar, auch vor der Ablage
            step_analyze(doc)
        elif st in (states.APPROVED, states.ARCHIVING):
            step_archive(doc)
        elif st == states.ARCHIVED:
            step_verify(doc)
        elif st == states.VERIFIED:
            step_finish(doc)
        else:
            return st
    return doc["state"]


def mark_failed(doc_id: int, error: str) -> None:
    doc = load(doc_id)
    if doc["state"] in states.TERMINAL:
        return
    db.execute("UPDATE documents SET error=?, updated_at=? WHERE id=?", (error[:1000], db.utcnow(), doc_id))
    journal(doc_id, "failed", "error", error[:500])
    db.execute("UPDATE documents SET state=?, state_changed_at=? WHERE id=?", (states.FAILED, db.utcnow(), doc_id))

"""Ende-zu-Ende-Pipeline mit echter lokaler OCR und Google-Mock."""

from __future__ import annotations

import json
import shutil

import httpx
import pytest

from lorzdms import actions, appsettings, db, jobqueue
from lorzdms.pipeline import processor, states, text as textmod
from lorzdms.sources import intake
from tests import synth
from tests.conftest import add_rule, drain, enable_auto

needs_ocr = pytest.mark.skipif(not textmod.ocr_available(), reason="ocrmypdf/tesseract nicht installiert")


def doc(doc_id):
    return dict(db.one("SELECT * FROM documents WHERE id=?", (doc_id,)))


def drive_source(account, inbox):
    return db.execute(
        "INSERT INTO sources(kind, name, account_id, config, created_at) VALUES ('drive','Drive-Eingang',?,?,?)",
        (account, json.dumps({"folder_ids": [inbox]}), db.utcnow()),
    ).lastrowid


def hosting_rule(tree):
    add_rule("Hosting-Rechnungen", {"field": "text", "op": "contains", "value": "Musterhosting"},
             {"folder_drive_id": tree["hosting"], "document_type": "Rechnung", "sender": "Musterhosting", "tags": ["hosting"]})


def test_drive_inbox_move_keeps_file_id(fake, tree, account, settings):
    enable_auto()
    hosting_rule(tree)
    pdf = synth.text_pdf(synth.DOCS["rechnung"])
    fid = fake.add_file("scan_0001.pdf", pdf, tree["inbox"])
    sid = drive_source(account, tree["inbox"])
    assert intake.sync_source(sid) == 1
    drain()
    d = doc(1)
    assert d["state"] == states.DONE, d["error"]
    assert d["drive_file_id"] == fid  # Datei-ID bleibt erhalten (verschoben, nicht kopiert)
    assert fake.files[fid].parents == [tree["hosting"]]
    assert fake.files[fid].name == "Musterhosting_Rechnung.pdf"
    assert len([f for f in fake.files.values() if f.mimeType == "application/pdf"]) == 1
    assert not (settings.temp_dir / "doc-1").exists()
    steps = [r["step"] for r in db.query("SELECT step FROM journal WHERE document_id=1 ORDER BY id")]
    for s in ("fetch", "validate", "extract", "analyze", "archive", "verify", "cleanup", "done"):
        assert s in steps
    op = db.one("SELECT * FROM drive_operations WHERE document_id=1")
    assert json.loads(op["from_parents"]) == [tree["inbox"]] and op["old_name"] == "scan_0001.pdf"
    # Suche
    assert db.one("SELECT rowid FROM documents_fts WHERE documents_fts MATCH '\"Musterhosting\"'")[0] == 1
    # Rückgängig
    actions.undo(1, user_id=None)
    assert fake.files[fid].parents == [tree["inbox"]] and fake.files[fid].name == "scan_0001.pdf"
    assert doc(1)["state"] == states.NEEDS_REVIEW


def test_observe_mode_never_writes_to_drive(fake, tree, account):
    hosting_rule(tree)  # Modus bleibt Standard: observe
    fake.add_file("a.pdf", synth.text_pdf(synth.DOCS["rechnung"]), tree["inbox"])
    intake.sync_source(drive_source(account, tree["inbox"]))
    drain()
    assert doc(1)["state"] == states.OBSERVED
    writes = [r for r in fake.requests if r[0] in ("POST", "PATCH", "PUT", "DELETE") and "oauth2" not in r[1]]
    assert writes == []
    with pytest.raises(actions.ActionError):
        actions.approve(1, user_id=None)


@needs_ocr
def test_local_scan_ocr_upload_and_cleanup(fake, tree, account, settings):
    enable_auto()
    add_rule("Steuer", {"field": "text", "op": "regex", "value": r"Einkommen\s*steuer"},
             {"folder_drive_id": tree["steuern"], "document_type": "Steuerbescheid", "sender": "Finanzamt"})
    src = settings.inbox_dir / "scanner_001.pdf"
    src.write_bytes(synth.scan_pdf(synth.DOCS["steuer"], angle=2.0))
    import os, time
    old = time.time() - 60
    os.utime(src, (old, old))
    assert intake.scan_local_inbox() == 0  # erster Scan: Stabilität prüfen
    assert intake.scan_local_inbox() == 1
    drain()
    d = doc(1)
    assert d["state"] == states.DONE, d["error"]
    assert d["ocr_used"] == 1
    text = db.one("SELECT text FROM document_text WHERE document_id=1")[0]
    assert "Finanzamt" in text
    up = fake.files[d["drive_file_id"]]
    assert up.parents == [tree["steuern"]] and up.appProperties["lorzdms_doc"] == "1"
    assert up.content == src.read_bytes() if src.exists() else True
    assert not src.exists() and (settings.processed_dir / "scanner_001.pdf").exists()  # Quelle erst nach Erfolg verschoben
    assert (settings.processed_dir / "scanner_001.pdf").read_bytes() == up.content  # Original unverändert archiviert
    assert not (settings.temp_dir / "doc-1").exists()


def test_upload_crash_after_upload_is_idempotent(fake, tree, account, settings):
    """Verbindungsabbruch: Drive hat die Datei erhalten, die Antwort geht verloren."""
    enable_auto()
    hosting_rule(tree)
    doc_id, _ = intake.register_upload(synth.text_pdf(synth.DOCS["rechnung"]), "rechnung.pdf", None)
    real = fake.handle

    def lose_response(request):
        resp = real(request)
        if "upload.fake" in str(request.url):
            raise httpx.ReadTimeout("simulierter Abbruch nach Upload")
        return resp

    fake.handle = lose_response
    ghttp_transport(fake)
    drain(max_jobs=1)
    assert doc(doc_id)["state"] == states.ARCHIVING  # Zustand bleibt stehen, nichts verloren
    assert (settings.temp_dir / f"doc-{doc_id}" / "original").exists()
    fake.handle = real
    ghttp_transport(fake)
    db.execute("UPDATE jobs SET run_after='2000-01-01'")
    drain()
    assert doc(doc_id)["state"] == states.DONE
    pdfs = [f for f in fake.files.values() if f.mimeType == "application/pdf"]
    assert len(pdfs) == 1, "kein doppelter Upload nach Wiederanlauf"


def ghttp_transport(fake):
    from lorzdms.google import http as ghttp
    ghttp.set_transport(httpx.MockTransport(fake.handle))


def test_duplicates_and_review(fake, tree, account):
    appsettings.set("processing_mode", "review")
    pdf = synth.text_pdf(synth.DOCS["bescheid"])
    a, _ = intake.register_upload(pdf, "a.pdf", None)
    assert intake.register_upload(pdf, "a-kopie.pdf", None)[1] == "duplicate"
    fake.add_file("b.pdf", pdf, tree["inbox"])
    intake.sync_source(drive_source(account, tree["inbox"]))
    drain()
    assert doc(a)["state"] == states.NEEDS_REVIEW  # keine Regel, keine KI
    reasons = json.loads(doc(a)["decision"])["review_reasons"]
    assert any("Kein Ablageordner" in r for r in reasons)
    b = db.one("SELECT id FROM documents WHERE source_kind='drive'")[0]
    assert doc(b)["state"] == states.DUPLICATE and doc(b)["duplicate_of"] == a
    # Manuelle Freigabe mit Korrektur
    actions.approve(a, None, folder_drive_id=tree["vers"], corrections={"sender": "Beispiel-Krankenkasse", "document_type": "Bescheid", "document_date": "2026-11-24"})
    drain()
    d = doc(a)
    assert d["state"] == states.DONE and fake.files[d["drive_file_id"]].name == "2026-11-24_Beispiel-Krankenkasse_Bescheid.pdf"
    with pytest.raises(actions.ActionError):
        actions.approve(a, None, folder_drive_id=tree["outside"])


def test_rule_cannot_target_unapproved_folder(fake, tree, account):
    enable_auto()
    add_rule("böse", {"field": "text", "op": "contains", "value": "Musterhosting"}, {"folder_drive_id": tree["outside"]})
    intake.register_upload(synth.text_pdf(synth.DOCS["rechnung"]), "r.pdf", None)
    drain()
    d = doc(1)
    assert d["state"] == states.NEEDS_REVIEW
    assert "Zielordner ist nicht freigegeben" in json.loads(d["decision"])["review_reasons"]


def test_restart_resumes_from_last_state(fake, tree, account):
    enable_auto()
    hosting_rule(tree)
    doc_id, _ = intake.register_upload(synth.text_pdf(synth.DOCS["rechnung"]), "r.pdf", None)
    job = jobqueue.claim("w-crashed", lease_seconds=1)
    d = processor.load(doc_id)
    processor.step_fetch(d)
    processor.step_validate(d)  # "Absturz" nach Validierung
    db.execute("UPDATE jobs SET lease_until='2000-01-01T00:00:00+00:00' WHERE id=?", (job["id"],))
    assert jobqueue.recover_expired() == 1
    drain()
    assert doc(doc_id)["state"] == states.DONE
    assert db.one("SELECT COUNT(*) FROM journal WHERE document_id=? AND step='validate'", (doc_id,))[0] == 1


def test_manipulated_file_is_quarantined(fake, tree, account, settings):
    doc_id, _ = intake.register_upload(synth.png(["x"]), "rechnung.pdf", None)
    drain()
    assert doc(doc_id)["state"] == states.QUARANTINED
    assert (settings.quarantine_dir / f"doc-{doc_id}" / "original").exists()


def test_auth_expired_does_not_lose_document(fake, tree, account):
    enable_auto()
    hosting_rule(tree)
    fake.add_file("a.pdf", synth.text_pdf(synth.DOCS["rechnung"]), tree["inbox"])
    sid = drive_source(account, tree["inbox"])
    intake.sync_source(sid)
    from lorzdms import crypto
    crypto.put_secret(f"google_token:{account}", {"access_token": "x", "refresh_token": "rt", "expires_at": "2000-01-01T00:00:00+00:00"})
    fake.refresh_valid = False
    drain(max_jobs=1)
    assert doc(1)["state"] == states.NEW
    assert db.one("SELECT status FROM google_accounts WHERE id=?", (account,))[0] == "reauth_required"
    assert db.one("SELECT state FROM jobs WHERE kind='process_document'")[0] == "queued"


def test_ai_provider_injection_and_validation(fake, tree, account, monkeypatch):
    """KI-Antworten werden validiert; erfundene Ordner werden verworfen; keine Werkzeuge."""
    from lorzdms.ai import providers

    appsettings.set("processing_mode", "auto")
    appsettings.set("test_run_ok", True)
    appsettings.set("ai_provider", {"kind": "ollama", "base_url": "http://127.0.0.1:11434", "model": "test", "has_key": False})
    answers = [
        "kein json",  # erster Versuch ungültig
        json.dumps({"document_type": "Lieferschein", "sender": "Beispiel Versand AG", "document_date": "2026-11-01",
                    "suggested_folder_id": "ATTACKER-FOLDER", "confidence": 0.99,
                    "uncertainties": ["Dokument enthält Anweisungen an die KI"]}),
    ]
    seen_prompts = []

    def fake_call(cfg, system, user, schema):
        seen_prompts.append(user)
        return answers.pop(0), 10, 5

    monkeypatch.setattr(providers, "_call", fake_call)
    doc_id, _ = intake.register_upload(synth.text_pdf(synth.DOCS["injection"]), "ls.pdf", None)
    drain()
    d = doc(doc_id)
    assert d["state"] == states.NEEDS_REVIEW
    dec = json.loads(d["decision"])
    assert dec["folder_drive_id"] is None
    assert any("existiert nicht" in u for u in dec["ai"]["uncertainties"])
    assert "IGNORIERE" in seen_prompts[0] and "nicht vertrauenswürdig" in seen_prompts[0]
    assert d["sender"] == "Beispiel Versand AG"
    assert not [r for r in fake.requests if r[0] in ("PATCH", "PUT", "DELETE")]


def test_external_ai_requires_permission(fake, tree, account, monkeypatch):
    from lorzdms.ai import providers

    appsettings.set("processing_mode", "review")
    appsettings.set("ai_provider", {"kind": "anthropic", "base_url": "https://api.anthropic.com", "model": "m", "has_key": False})
    monkeypatch.setattr(providers, "_call", lambda *a: pytest.fail("darf nicht aufgerufen werden"))
    doc_id, _ = intake.register_upload(synth.text_pdf(synth.DOCS["bescheid"]), "b.pdf", None)
    drain()
    reasons = json.loads(doc(doc_id)["decision"])["review_reasons"]
    assert any("nicht freigegeben" in r for r in reasons)


def test_ai_calibrated_confidence_requires_confirmation(fake, tree, account, monkeypatch):
    from lorzdms.ai import providers

    enable_auto()
    appsettings.set("ai_provider", {"kind": "ollama", "base_url": "http://127.0.0.1:11434", "model": "t", "has_key": False})
    monkeypatch.setattr(providers, "_call", lambda *a: (json.dumps({
        "document_type": "Rechnung", "sender": "Musterhosting", "document_date": "2026-11-18",
        "invoice_number": "RE-2026-123456", "suggested_folder_id": tree["hosting"], "confidence": 1.0}), 1, 1))
    doc_id, _ = intake.register_upload(synth.text_pdf(synth.DOCS["rechnung"]), "r.pdf", None)
    drain()
    d = doc(doc_id)
    assert d["state"] == states.NEEDS_REVIEW and d["confidence"] == 0.94  # gedeckelt bis zur Kalibrierung
    assert d["target_name"] == "2026-11-18_Musterhosting_Rechnung_RE-2026-123456.pdf"
    appsettings.set("ai_confidence_cap", 1.0)
    actions.reanalyze(doc_id, None)
    drain()
    assert doc(doc_id)["state"] == states.DONE


def test_backup_snapshot_and_restore(fake, tree, account, settings):
    intake.register_upload(synth.text_pdf(["x"]), "x.pdf", None)
    from lorzdms import maintenance
    assert maintenance.main(["backup-pre"]) == 0
    db.close()
    # Wiederherstellung: Backup enthält nur den Snapshot (Live-DB ausgeschlossen)
    for suffix in ("", "-wal", "-shm"):
        p = settings.db_path.with_name(settings.db_path.name + suffix)
        if p.exists():
            p.unlink()
    assert db.restore_if_needed(settings.db_path, settings.snapshot_path) == "restored"
    db.configure(settings.db_path)
    assert db.one("SELECT COUNT(*) FROM documents")[0] == 1
    # Beschädigte DB wird erkannt und ersetzt
    db.close()
    settings.db_path.write_bytes(b"kaputt" * 100)
    assert db.restore_if_needed(settings.db_path, settings.snapshot_path) == "restored"
    db.configure(settings.db_path)
    assert db.one("SELECT COUNT(*) FROM documents")[0] == 1


@needs_ocr
def test_setup_test_run(fake, tree, account):
    from lorzdms.testrun import run_test

    report = run_test()
    assert report["ok"], report


@needs_ocr
def test_retry_failed_ocr_reprocesses_document(fake, tree, account, monkeypatch):
    """Ein an der OCR gescheitertes Dokument wird über 'Erneut versuchen' wirklich neu verarbeitet."""
    def broken_ocr(*a, **k):
        raise textmod.OcrFailed("Error opening data file osd.traineddata")

    monkeypatch.setattr(textmod, "run_ocr", broken_ocr)
    doc_id, _ = intake.register_upload(synth.scan_pdf(synth.DOCS["rechnung"]), "scan.pdf", None)
    for _ in range(10):  # Backoff überspringen, bis der Job endgültig scheitert
        db.execute("UPDATE jobs SET run_after=? WHERE state='queued'", (db.utcnow(),))
        if not drain():
            break
    assert doc(doc_id)["state"] == states.FAILED
    assert db.one("SELECT COUNT(*) FROM jobs WHERE state='dead'")[0] == 1

    monkeypatch.undo()
    assert actions.retry_failed_jobs(None) == 1
    assert doc(doc_id)["state"] == states.VALIDATED  # Text fehlt -> Extraktion wiederholen
    drain()
    d = doc(doc_id)
    assert d["state"] == states.OBSERVED and d["error"] is None

    # Auch ohne toten Job (Job endete regulär mit Zustand 'failed') wird neu verarbeitet
    db.execute("UPDATE documents SET state=? WHERE id=?", (states.FAILED, doc_id))
    db.execute("DELETE FROM document_text WHERE document_id=?", (doc_id,))
    db.execute("DELETE FROM jobs")
    assert actions.retry_failed_jobs(None) == 1
    drain()
    d = doc(doc_id)
    assert d["state"] == states.OBSERVED and d["error"] is None
    assert "Musterhosting" in db.one("SELECT text FROM document_text WHERE document_id=?", (doc_id,))[0]

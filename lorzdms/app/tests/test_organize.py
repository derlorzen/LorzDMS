"""Fristen, Erinnerungen, Vorgänge und Tags."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone

import httpx
import pytest
from fastapi.testclient import TestClient

from lorzdms import appsettings, db, jobqueue, notify, organize, worker
from lorzdms.api.app import create_app
from lorzdms.sources import intake
from tests import synth
from tests.conftest import drain
from tests.test_api import H1, H2


def make_doc(title="Dok", tags=None, visibility="members", sender="Musterhosting", document_type="Rechnung") -> int:
    now = db.utcnow()
    doc_id, _ = intake.register_upload(synth.text_pdf([title]), f"{title}.pdf", None)
    db.execute("UPDATE documents SET title=?, tags=?, visibility=?, sender=?, document_type=?, updated_at=? WHERE id=?",
               (title, json.dumps(tags or []), visibility, sender, document_type, now, doc_id))
    return doc_id


def load(doc_id):
    d = dict(db.one("SELECT * FROM documents WHERE id=?", (doc_id,)))
    d["metadata"] = json.loads(d["metadata"] or "{}")
    return d


@pytest.fixture()
def client(settings, fake):
    c = TestClient(create_app(init=False))
    c.get("/api/me", headers=H1)
    return c


# Fristen ------------------------------------------------------------------------

def test_deadlines_from_analysis_are_idempotent_and_respect_dismissal(settings):
    doc_id = make_doc()
    meta = {"due_date": "2026-12-02", "amount": 11.9, "document_type": "Rechnung",
            "deadlines": [{"kind": "objection", "date": "2026-12-24", "explicit": False, "quote": "innerhalb eines Monats"},
                          {"kind": "bogus", "date": "kein Datum"}]}
    assert organize.sync_from_analysis(load(doc_id), meta) == 2
    rows = db.query("SELECT * FROM deadlines WHERE document_id=? ORDER BY due_date", (doc_id,))
    assert [(r["kind"], r["due_date"], r["explicit"]) for r in rows] == [("payment", "2026-12-02", 1), ("objection", "2026-12-24", 0)]
    assert rows[0]["title"] == "Zahlung: Musterhosting – Rechnung"
    organize.update_deadline(rows[0]["id"], {"status": "dismissed"})
    assert organize.sync_from_analysis(load(doc_id), meta) == 0  # erneute Analyse legt nichts doppelt an
    assert db.one("SELECT status FROM deadlines WHERE id=?", (rows[0]["id"],))["status"] == "dismissed"


def test_reminder_stages(settings):
    did = organize.create_deadline(title="Kfz-Versicherung kündigen", due_date="2026-12-10", kind="cancellation", remind_days=5)
    sent: list[tuple] = []
    notifier = lambda title, msg, tag: sent.append((title, msg, tag))  # noqa: E731
    assert organize.run_reminders(notifier, date(2026, 12, 1)) == 0  # vor dem Vorlauf
    assert organize.run_reminders(notifier, date(2026, 12, 5)) == 1  # Vorab-Erinnerung
    assert sent[-1] == ("LorzDMS: Frist", "Kfz-Versicherung kündigen – fällig in 5 Tag(en) am 10.12.2026", f"lorzdms_deadline_{did}")
    assert organize.run_reminders(notifier, date(2026, 12, 6)) == 0  # nicht doppelt
    assert organize.run_reminders(notifier, date(2026, 12, 11)) == 1  # Fälligkeit/überfällig
    assert "überfällig" in sent[-1][1]
    assert organize.run_reminders(notifier, date(2026, 12, 20)) == 0
    # Datum verschoben -> Erinnerungen beginnen neu
    organize.update_deadline(did, {"due_date": "2027-01-15"})
    assert organize.run_reminders(notifier, date(2027, 1, 10)) == 1
    organize.update_deadline(did, {"status": "done"})
    assert organize.run_reminders(notifier, date(2027, 1, 20)) == 0


def test_notifier_failure_keeps_reminder_pending(settings):
    organize.create_deadline(title="Zahlung", due_date="2026-12-01")

    def broken(*_a):
        raise notify.NotifyError("weg")

    with pytest.raises(notify.NotifyError):
        organize.run_reminders(broken, date(2026, 12, 1))
    assert organize.run_reminders(lambda *a: None, date(2026, 12, 1)) == 1


def test_notify_send_uses_supervisor_core_api(settings, monkeypatch):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=[])

    monkeypatch.delenv("SUPERVISOR_TOKEN", raising=False)
    with pytest.raises(notify.NotifyError):
        notify.send("t", "m", "x", transport=httpx.MockTransport(handler))
    monkeypatch.setenv("SUPERVISOR_TOKEN", "tok")
    notify.send("t", "m", "lorzdms_deadline_1", transport=httpx.MockTransport(handler))
    assert seen["url"] == "http://supervisor/core/api/services/persistent_notification/create"
    assert seen["auth"] == "Bearer tok"
    assert seen["body"] == {"title": "t", "message": "m", "notification_id": "lorzdms_deadline_1"}
    notify.send("t", "m", "x", service="notify.mobile_app_pixel", transport=httpx.MockTransport(handler))
    assert seen["url"].endswith("/services/notify/mobile_app_pixel") and seen["body"]["data"]["tag"] == "x"
    for bad in ("homeassistant.restart", "notify.", "notify.x/../y", "shell_command.rm"):
        with pytest.raises(ValueError):
            notify.validate_service(bad)


def test_worker_schedules_and_runs_reminders(settings, monkeypatch):
    organize.create_deadline(title="Heute", due_date=date.today().isoformat())
    noon = datetime.now().astimezone().replace(hour=12)
    monkeypatch.delenv("SUPERVISOR_TOKEN", raising=False)
    assert worker.schedule_reminders(noon) is False
    assert db.get_setting("reminders_last_run")["status"] == "unavailable"
    monkeypatch.setenv("SUPERVISOR_TOKEN", "tok")
    assert worker.schedule_reminders(noon.replace(hour=5)) is False  # vor reminder_hour
    assert worker.schedule_reminders(noon) is True
    assert worker.schedule_reminders(noon) is False  # höchstens alle 30 Minuten
    sent = []
    monkeypatch.setattr(notify, "send", lambda *a, **k: sent.append(a))
    drain()
    assert len(sent) == 1 and db.get_setting("reminders_last_run")["sent"] == 1
    assert jobqueue.stats()  # Job erledigt, nicht tot
    assert db.one("SELECT COUNT(*) n FROM jobs WHERE kind='deadline_reminders' AND state='dead'")["n"] == 0


# Vorgänge -----------------------------------------------------------------------

def test_auto_link_by_reference_and_deadline_inherits_case(settings):
    case_id = organize.create_case("Pflegekasse Pflegegrad", reference="pk-4711/26")
    closed = organize.create_case("Alt", reference="PK-4711/26")
    organize.update_case(closed, {"status": "closed"})
    doc_id = make_doc("Bescheid")
    meta = {"case_number": "PK 4711/26", "deadlines": [{"kind": "objection", "date": "2026-12-24", "explicit": True}]}
    assert organize.auto_link(load(doc_id), meta) == [case_id]  # nur offene Vorgänge
    organize.sync_from_analysis(load(doc_id), meta)
    assert db.one("SELECT case_id FROM deadlines WHERE document_id=?", (doc_id,))["case_id"] == case_id
    assert organize.auto_link(load(doc_id), {"case_number": "PK"}) == []  # zu kurze Referenzen nie
    assert [c["source"] for c in organize.cases_for_document(doc_id)] == ["auto"]


def test_processing_creates_deadlines_and_links_case(fake, tree, account, monkeypatch):
    from lorzdms.ai import providers

    appsettings.set("ai_provider", {"kind": "ollama", "base_url": "http://127.0.0.1:11434", "model": "t", "has_key": False})
    monkeypatch.setattr(providers, "_call", lambda *a: (json.dumps({
        "document_type": "Rechnung", "sender": "Musterhosting", "document_date": "2026-11-18", "due_date": "2026-12-02",
        "amount": 11.9, "customer_number": "K-998877", "suggested_folder_id": tree["hosting"], "confidence": 0.9}), 1, 1))
    case_id = organize.create_case("Hosting", reference="K-998877")
    doc_id, _ = intake.register_upload(synth.text_pdf(synth.DOCS["rechnung"]), "r.pdf", None)
    drain()
    dl = db.one("SELECT * FROM deadlines WHERE document_id=?", (doc_id,))
    assert dl["kind"] == "payment" and dl["due_date"] == "2026-12-02" and dl["case_id"] == case_id
    assert db.one("SELECT step FROM journal WHERE document_id=? AND step='organize'", (doc_id,)) is not None


# Tags ---------------------------------------------------------------------------

def test_tags_normalize_count_rename(settings):
    a = make_doc("A", tags=["Steuer 2025", "Auto"])
    b = make_doc("B", tags=["steuer 2025"])
    assert organize.set_tags(b, [" Steuer  2025 ", "steuer 2025", "Haus"]) == ["Steuer 2025", "Haus"]
    with pytest.raises(organize.OrganizeError):
        organize.normalize_tag("<script>")
    counts = {c["tag"]: c["count"] for c in organize.tag_counts()}
    assert counts == {"Steuer 2025": 2, "Auto": 1, "Haus": 1}
    assert organize.rename_tag("Auto", "Haus") == 1  # Zusammenführen
    assert json.loads(load(a)["tags"]) == ["Steuer 2025", "Haus"]
    assert organize.rename_tag("Haus", None) == 2  # Entfernen
    assert json.loads(load(b)["tags"]) == ["Steuer 2025"]


# API ----------------------------------------------------------------------------

def test_api_deadlines_cases_tags_and_visibility(client):
    pub = make_doc("Öffentlich", tags=["Auto"])
    secret = make_doc("Geheim", tags=["Gesundheit"], visibility="admins")
    r = client.post("/api/deadlines", json={"title": "TÜV", "due_date": "2026-12-15", "kind": "appointment", "document_id": pub}, headers=H1)
    assert r.status_code == 200 and r.json()["document_title"] == "Öffentlich"
    client.post("/api/deadlines", json={"title": "Arztrechnung", "due_date": "2026-12-01", "document_id": secret}, headers=H1)
    assert client.post("/api/deadlines", json={"due_date": "2026-13-01"}, headers=H1).status_code == 400
    c = client.post("/api/cases", json={"title": "Auto", "reference": "WOB-123", "document_ids": [pub]}, headers=H1).json()
    assert c["document_count"] == 1 and c["reference"] == "WOB-123"
    assert client.get(f"/api/documents?case_id={c['id']}", headers=H1).json()["total"] == 1
    assert client.get("/api/documents?tag=Auto", headers=H1).json()["total"] == 1
    detail = client.get(f"/api/documents/{pub}", headers=H1).json()
    assert detail["cases"][0]["id"] == c["id"] and detail["deadlines"][0]["title"] == "TÜV"
    assert client.get("/api/dashboard", headers=H1).json()["deadlines"]["open"] == 2

    # zweiter Benutzer (Leserecht) sieht die geheime Frist und den geheimen Tag nicht und darf nichts ändern
    client.get("/api/me", headers=H2)
    uid = db.one("SELECT id FROM users WHERE ha_user_id='ha-other'")[0]
    client.patch(f"/api/users/{uid}", json={"role": "viewer"}, headers=H1)
    titles = [d["title"] for d in client.get("/api/deadlines", headers=H2).json()["items"]]
    assert titles == ["TÜV"]
    assert [t["tag"] for t in client.get("/api/tags", headers=H2).json()["items"]] == ["Auto"]
    assert client.put(f"/api/documents/{pub}/tags", json={"tags": ["x"]}, headers=H2).status_code == 403
    client.patch(f"/api/users/{uid}", json={"role": "editor"}, headers=H1)
    assert client.put(f"/api/documents/{secret}/tags", json={"tags": ["x"]}, headers=H2).status_code == 404  # kein IDOR
    assert client.post(f"/api/cases/{c['id']}/documents", json={"document_id": secret}, headers=H2).status_code == 404
    assert client.put(f"/api/documents/{pub}/tags", json={"tags": ["Auto", "Kfz"]}, headers=H2).json() == {"tags": ["Auto", "Kfz"]}
    assert client.post("/api/tags/rename", json={"old": "Kfz", "new": "Auto"}, headers=H2).status_code == 403

    # erledigen, verwerfen, löschen
    tuv = client.get("/api/deadlines", headers=H1).json()["items"][1]
    assert client.patch(f"/api/deadlines/{tuv['id']}", json={"status": "done"}, headers=H1).json()["status"] == "done"
    assert client.patch(f"/api/deadlines/{tuv['id']}", json={"document_id": secret}, headers=H1).status_code == 400
    assert client.delete(f"/api/deadlines/{tuv['id']}", headers=H1).json() == {"ok": True}
    assert client.get("/api/deadlines?status=all", headers=H1).json()["summary"]["open"] == 1

    # Vorgang abschließen und löschen lässt Dokumente unberührt
    assert client.patch(f"/api/cases/{c['id']}", json={"status": "closed"}, headers=H1).json()["closed_at"]
    assert client.delete(f"/api/cases/{c['id']}", headers=H1).json() == {"ok": True}
    assert db.one("SELECT COUNT(*) n FROM documents")["n"] == 2


def test_api_reminder_settings_validation(client):
    assert client.patch("/api/settings", json={"notify_service": "homeassistant.restart"}, headers=H1).status_code == 400
    assert client.patch("/api/settings", json={"reminder_hour": 25}, headers=H1).status_code == 400
    s = client.patch("/api/settings", json={"notify_service": "notify.mobile_app_pixel", "reminder_days_default": 7}, headers=H1).json()
    assert s["notify_service"] == "notify.mobile_app_pixel" and s["reminder_days_default"] == 7
    st = client.get("/api/deadlines/notify-status", headers=H1).json()
    assert st["service"] == "notify.mobile_app_pixel"


def test_migration_backfills_only_future_deadlines(settings):
    from datetime import timedelta
    from importlib import resources

    future = (date.today() + timedelta(days=10)).isoformat()
    a = make_doc("Zukunft")
    b = make_doc("Vergangen", sender=None, document_type="Bescheid")
    db.execute("UPDATE documents SET metadata=? WHERE id=?", (json.dumps({"due_date": future, "amount": 5}), a))
    db.execute("UPDATE documents SET metadata=? WHERE id=?", (json.dumps({"due_date": "2020-01-01", "deadlines": [
        {"kind": "objection", "date": future, "explicit": False, "quote": "innerhalb eines Monats"},
        {"kind": "response", "date": "2021-01-01"}]}), b))
    sql = resources.files("lorzdms.migrations").joinpath("0002_fristen_vorgaenge.sql").read_text("utf-8")
    for stmt in db._split_sql(sql):
        if stmt.lstrip().startswith("INSERT"):
            db.execute(stmt)
    rows = [dict(r) for r in db.query("SELECT document_id, title, kind, due_date, explicit, quote FROM deadlines ORDER BY document_id")]
    assert rows == [
        {"document_id": a, "title": "Zahlung: Musterhosting – Rechnung", "kind": "payment", "due_date": future, "explicit": 1, "quote": None},
        {"document_id": b, "title": "Widerspruch: Bescheid", "kind": "objection", "due_date": future, "explicit": 0, "quote": "innerhalb eines Monats"},
    ]

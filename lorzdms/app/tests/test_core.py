"""Datenbank, Queue, Regeln, Dateinamen, Dateitypen."""

from __future__ import annotations

import threading
from datetime import datetime

import pytest

from lorzdms import db, jobqueue
from lorzdms.pipeline import filetypes, naming, rules, states
from lorzdms.resources import in_window
from tests import synth


def test_migrations_and_wal(settings):
    assert db.one("SELECT journal_mode FROM pragma_journal_mode")[0] == "wal"
    assert db.one("SELECT COUNT(*) FROM schema_migrations")[0] >= 1
    assert db.migrate() == []  # idempotent


def test_queue_dedupe_claim_retry_dead(settings):
    j1 = jobqueue.enqueue("x", {"a": 1}, dedupe_key="k")
    assert jobqueue.enqueue("x", {"a": 2}, dedupe_key="k") is None
    job = jobqueue.claim("w1")
    assert job["id"] == j1 and job["payload"] == {"a": 1} and job["attempts"] == 1
    assert jobqueue.claim("w2") is None
    assert jobqueue.fail(j1, "boom") == "queued"
    assert db.one("SELECT run_after FROM jobs WHERE id=?", (j1,))[0] > db.utcnow()
    db.execute("UPDATE jobs SET attempts=max_attempts, run_after='2000-01-01' WHERE id=?", (j1,))
    jobqueue.claim("w1")
    assert jobqueue.fail(j1, "boom") == "dead"
    assert jobqueue.retry_dead() == 1


def test_queue_priority_and_lease_recovery(settings):
    low = jobqueue.enqueue("bulk", priority=500)
    high = jobqueue.enqueue("new", priority=100)
    job = jobqueue.claim("w", lease_seconds=1)
    assert job["id"] == high
    db.execute("UPDATE jobs SET lease_until='2000-01-01T00:00:00+00:00' WHERE id=?", (high,))
    assert jobqueue.recover_expired() == 1
    assert jobqueue.claim("w")["id"] == high
    assert jobqueue.claim("w")["id"] == low


def test_concurrent_claim_is_exclusive(settings):
    for i in range(30):
        jobqueue.enqueue("c", {"i": i})
    claimed: list[int] = []
    lock = threading.Lock()

    def worker(name):
        while True:
            j = jobqueue.claim(name)
            if j is None:
                return
            with lock:
                claimed.append(j["id"])

    ts = [threading.Thread(target=worker, args=(f"w{i}",)) for i in range(4)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert len(claimed) == 30 and len(set(claimed)) == 30


def test_state_machine_rejects_invalid():
    states.check(states.NEW, states.FETCHED)
    with pytest.raises(states.InvalidTransition):
        states.check(states.NEW, states.DONE)


def test_rules_engine():
    cond = {"all": [
        {"field": "sender_domain", "op": "equals", "value": "musterhosting.de"},
        {"any": [{"field": "text", "op": "contains", "value": "Rechnung"}, {"field": "subject", "op": "regex", "value": r"RE-\d+"}]},
    ]}
    rules.validate_conditions(cond)
    ctx = {"sender_domain": "musterhosting.de", "text": "Ihre RECHNUNG", "subject": ""}
    assert rules.evaluate(cond, ctx)
    assert not rules.evaluate(cond, {**ctx, "sender_domain": "other.de"})
    r = [
        {"id": 1, "name": "A", "priority": 10, "enabled": True, "conditions": cond, "actions": {"folder_drive_id": "f1", "tags": ["x"]}, "stop_processing": False},
        {"id": 2, "name": "B", "priority": 20, "enabled": True, "conditions": {"field": "text", "op": "contains", "value": "rechnung"}, "actions": {"folder_drive_id": "f2"}, "stop_processing": True},
    ]
    out = rules.apply_rules(r, ctx)
    assert out.actions["folder_drive_id"] == "f1"  # höhere Priorität gewinnt
    assert out.conflicts  # widersprüchliche Regel wird gemeldet
    with pytest.raises(rules.RuleError):
        rules.validate_conditions({"field": "password", "op": "equals", "value": 1})
    with pytest.raises(rules.RuleError):
        rules.validate_actions({"delete": True})


def test_naming():
    meta = {"document_date": "18.11.2026", "sender": "Muster/Hosting: GmbH", "document_type": "Rechnung", "reference": "123456"}
    assert naming.render(naming.DEFAULT_TEMPLATE, meta, "scan.pdf", ".pdf") == "2026-11-18_Muster_Hosting_GmbH_Rechnung_123456.pdf"
    assert naming.render(naming.DEFAULT_TEMPLATE, {"sender": "AOK", "document_type": "Bescheid"}, "x.pdf", ".PDF") == "AOK_Bescheid.pdf"
    assert naming.render(naming.DEFAULT_TEMPLATE, {}, "Scan 001.pdf", ".pdf") == "Scan_001.pdf"
    assert len(naming.render("{title}", {"title": "A" * 400}, "x.pdf", ".pdf")) <= 154
    assert naming.resolve_conflict("a.pdf", {"a.pdf", "a_2.pdf"}) == "a_3.pdf"
    assert naming.validate_template("{__class__}")
    assert naming.validate_template("{sender!r}")


def test_filetypes(tmp_path):
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(synth.text_pdf(["Hallo"]))
    assert filetypes.validate(pdf, "a.pdf", 10**7, 10**8).mime == "application/pdf"
    fake = tmp_path / "rechnung.pdf"
    fake.write_bytes(b"MZ\x90\x00" + b"\x00" * 100)  # ausführbare Datei als .pdf getarnt
    v = filetypes.validate(fake, "rechnung.pdf", 10**7, 10**8)
    assert not v.ok
    png = tmp_path / "bild.pdf"
    png.write_bytes(synth.png(["x"]))
    v = filetypes.validate(png, "bild.pdf", 10**7, 10**8)
    assert not v.ok and v.quarantine  # Endung passt nicht zum Inhalt
    big = tmp_path / "b.pdf"
    big.write_bytes(synth.text_pdf(["x"]))
    assert not filetypes.validate(big, "b.pdf", 10, 10**8).ok
    bomb = tmp_path / "bomb.png"
    bomb.write_bytes(synth.png(["x"]))
    assert not filetypes.validate(bomb, "bomb.png", 10**7, 1000).ok


def test_processing_window():
    assert in_window("22:00-06:00", datetime(2026, 1, 1, 23, 0))
    assert not in_window("22:00-06:00", datetime(2026, 1, 1, 12, 0))
    assert in_window("", datetime(2026, 1, 1, 12, 0))


def test_provider_url_ssrf_guard(monkeypatch):
    import ipaddress

    from lorzdms.ai import providers

    table = {
        "supervisor": "172.30.32.2",
        "homeassistant": "172.30.32.1",
        "76e18fb5-ollama": "172.30.33.5",
        "metadata": "169.254.169.254",
        "lan": "192.168.1.20",
        "public": "93.184.216.34",
    }
    monkeypatch.setattr(providers, "_resolve", lambda h: [ipaddress.ip_address(table[h])])
    for host in ("supervisor", "homeassistant", "metadata"):
        with pytest.raises(providers.ProviderError):
            providers.check_url(f"http://{host}:11434")
    # Apps im Supervisor-App-Netz (z. B. Ollama) und LAN sind lokal und erlaubt
    assert providers.check_url("http://76e18fb5-ollama:11434") is True
    assert providers.check_url("http://lan:11434") is True
    with pytest.raises(providers.ProviderError):
        providers.check_url("http://public/v1")
    assert providers.check_url("https://public/v1") is False

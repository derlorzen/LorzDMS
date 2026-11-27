"""OAuth, Gmail (nur lesend), Drive-Schreibschutz – gegen den Google-Mock."""

from __future__ import annotations

import json

import pytest

from lorzdms import db, services
from lorzdms.google import drive as gdrive
from lorzdms.google import http as ghttp
from lorzdms.google import oauth
from lorzdms.sources import intake
from tests import synth


def test_client_json_validation():
    good = {"installed": {"client_id": "1-abc.apps.googleusercontent.com", "client_secret": "x", "redirect_uris": ["http://localhost"]}}
    assert oauth.parse_client_json(json.dumps(good))["client_type"] == "installed"
    web = {"web": {"client_id": "1-abc.apps.googleusercontent.com", "client_secret": "x", "redirect_uris": ["https://ha.example/cb"]}}
    cfg = oauth.parse_client_json(json.dumps(web))
    assert oauth.redirect_uri_problems(cfg, "http://127.0.0.1:8765/oauth2callback")  # nicht eingetragen
    assert not oauth.redirect_uri_problems(cfg, "https://ha.example/cb")
    for bad in ("nojson", json.dumps({"type": "service_account"}), json.dumps({"installed": {"client_id": "x"}}),
                json.dumps({"installed": {"client_id": "evil", "client_secret": "s"}})):
        with pytest.raises(oauth.OAuthConfigError):
            oauth.parse_client_json(bad)


def test_oauth_pkce_flow_and_refresh(fake, settings):
    oauth.save_client({"client_type": "installed", "client_id": "1.apps.googleusercontent.com", "client_secret": "s", "redirect_uris": []})
    url = oauth.start_authorization(settings.oauth_redirect_uri, oauth.scopes_for("full", True), None)
    assert "code_challenge_method=S256" in url and "gmail.readonly" in url and "access_type=offline" in url
    state = url.split("state=")[1].split("&")[0]
    with pytest.raises(oauth.OAuthConfigError):
        oauth.complete_authorization("good-code", "wrong-state")
    code, st = oauth.parse_redirect(f"http://127.0.0.1:8765/oauth2callback?state={state}&code=good-code&scope=x")
    res = oauth.complete_authorization(code, st)
    assert res["email"] == "test@example.org" and res["missing_scopes"] == []
    # state ist einmalig
    with pytest.raises(oauth.OAuthConfigError):
        oauth.complete_authorization(code, st)
    # Token in der DB verschlüsselt, nicht im Klartext
    blob = db.one("SELECT ciphertext FROM secrets WHERE key=?", (f"google_token:{res['account_id']}",))[0]
    assert b"rt-1" not in blob
    # Ablauf erzwingen -> Refresh
    from lorzdms import crypto
    tok = crypto.get_secret(f"google_token:{res['account_id']}")
    tok["expires_at"] = "2000-01-01T00:00:00+00:00"
    crypto.put_secret(f"google_token:{res['account_id']}", tok)
    assert oauth.access_token(res["account_id"]) == "at-2"
    # Widerrufenes Refresh-Token -> reauth_required
    tok = crypto.get_secret(f"google_token:{res['account_id']}")
    tok["expires_at"] = "2000-01-01T00:00:00+00:00"
    crypto.put_secret(f"google_token:{res['account_id']}", tok)
    fake.refresh_valid = False
    with pytest.raises(ghttp.AuthExpired):
        oauth.access_token(res["account_id"])
    assert db.one("SELECT status FROM google_accounts WHERE id=?", (res["account_id"],))[0] == "reauth_required"


def test_forbidden_gmail_scopes_rejected(fake, settings):
    oauth.save_client({"client_type": "installed", "client_id": "1.apps.googleusercontent.com", "client_secret": "s", "redirect_uris": []})
    with pytest.raises(oauth.OAuthConfigError):
        oauth.start_authorization(settings.oauth_redirect_uri, ["https://mail.google.com/"], None)


def test_gmail_readonly_import(fake, account):
    pdf = synth.text_pdf(synth.DOCS["rechnung"])
    m1 = fake.add_message(sender="Musterhosting <billing@musterhosting.de>", subject="Ihre Rechnung",
                          attachments=[("Rechnung.pdf", pdf, "application/pdf"), ("AGB.pdf", synth.text_pdf(["AGB"]), "application/pdf")],
                          inline_images=[("logo.png", b"\x89PNG" + b"0" * 50)])
    fake.add_message(sender="x@y.de", subject="ohne", attachments=[("bild.jpg", b"\xff\xd8\xff" + b"0" * 100, "image/jpeg")])
    sid = db.execute("INSERT INTO sources(kind, name, account_id, config, created_at) VALUES ('gmail','Gmail',?,?,?)",
                     (account, json.dumps({"query": "has:attachment"}), db.utcnow())).lastrowid
    assert intake.sync_source(sid) == 2  # 2 PDFs, Logo und JPG (nicht aktiviert) ausgeschlossen
    rows = db.query("SELECT source_ref, original_filename, email_meta FROM documents WHERE source_kind='gmail' ORDER BY id")
    assert [r["source_ref"] for r in rows] == [f"{m1}:1", f"{m1}:2"]
    meta = json.loads(rows[0]["email_meta"])
    assert meta["from_email"] == "billing@musterhosting.de" and meta["subject"] == "Ihre Rechnung"
    # Erneuter Lauf (History-API): keine Duplikate; neue Nachricht wird erkannt
    assert intake.sync_source(sid) == 0
    fake.add_message(sender="a@b.de", subject="neu", attachments=[("Neu.pdf", synth.text_pdf(["neu"]), "application/pdf")])
    assert intake.sync_source(sid) == 1
    gmail_calls = [(m, u) for m, u in fake.requests if "gmail.googleapis.com" in u]
    assert gmail_calls and all(m == "GET" for m, _ in gmail_calls), "Gmail darf nur gelesen werden"


def test_gmail_history_expired_falls_back(fake, account):
    fake.add_message(sender="a@b.de", subject="s", attachments=[("A.pdf", synth.text_pdf(["a"]), "application/pdf")])
    sid = db.execute("INSERT INTO sources(kind, name, account_id, config, cursor, created_at) VALUES ('gmail','G',?, '{}', '5', ?)",
                     (account, db.utcnow())).lastrowid
    assert intake.sync_source(sid) == 1


def test_gmail_deleted_message_in_history_is_skipped(fake, account):
    sid = db.execute("INSERT INTO sources(kind, name, account_id, config, created_at) VALUES ('gmail','G',?, '{}', ?)",
                     (account, db.utcnow())).lastrowid
    assert intake.sync_source(sid) == 0  # Erstlauf setzt den History-Cursor
    gone = fake.add_message(sender="a@b.de", subject="Entwurf", attachments=[("X.pdf", synth.text_pdf(["x"]), "application/pdf")])
    del fake.messages[gone]  # in der History gemeldet, danach gelöscht -> 404
    fake.add_message(sender="c@d.de", subject="echt", attachments=[("B.pdf", synth.text_pdf(["b"]), "application/pdf")])
    assert intake.sync_source(sid) == 1
    src = db.one("SELECT cursor FROM sources WHERE id=?", (sid,))
    assert src["cursor"] == str(fake.history_id)
    assert intake.sync_source(sid) == 0


def test_gmail_client_has_no_write_methods():
    from lorzdms.google.gmail import GmailClient

    public = {n for n in dir(GmailClient) if not n.startswith("_")}
    assert public <= {"profile", "list_labels", "search", "history", "message", "attachment"}


def test_drive_guard(fake, tree, account):
    guard = services.guard(account)
    f = fake.add_file("a.pdf", b"%PDF-1.4", tree["inbox"])
    outside = fake.add_file("b.pdf", b"%PDF-1.4", tree["outside"])
    with pytest.raises(gdrive.WriteNotAllowed):
        guard.move(f, tree["outside"], None)  # Ziel nicht freigegeben
    with pytest.raises(gdrive.WriteNotAllowed):
        guard.move(outside, tree["hosting"], None)  # Quelle nicht freigegeben
    with pytest.raises(gdrive.WriteNotAllowed):
        guard.ensure_folder("Neu", tree["inbox"])  # Eingang ist nicht beschreibbar
    sub = guard.ensure_folder("2026", tree["hosting"])
    assert guard.ensure_folder("2026", tree["hosting"])["id"] == sub["id"]  # keine Doppelanlage
    updated, old_parents, _ = guard.move(f, sub["id"], "neu.pdf")
    assert updated["id"] == f and old_parents == [tree["inbox"]] and fake.files[f].parents == [sub["id"]]
    assert not any(hasattr(guard, n) or hasattr(guard.client, n) for n in ("delete", "trash"))
    assert not [r for r in fake.requests if r[0] == "DELETE"]

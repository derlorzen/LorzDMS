"""REST-API: Ingress-Authentifizierung, Rollen, CSRF, Sichtbarkeit, Upload."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from lorzdms import db
from lorzdms.api.app import create_app
from tests import synth

H1 = {"X-Remote-User-Id": "ha-admin", "X-Remote-User-Name": "admin", "X-Requested-With": "lorzdms"}
H2 = {"X-Remote-User-Id": "ha-other", "X-Remote-User-Name": "kind", "X-Requested-With": "lorzdms"}


@pytest.fixture()
def client(settings, fake):
    return TestClient(create_app(init=False))


def test_requires_supervisor_proxy(client, settings):
    assert client.get("/api/me").status_code == 401  # keine Identität
    settings.trusted_proxy = "172.30.32.2"
    assert client.get("/api/me", headers=H1).status_code == 401  # Header von fremder IP ignoriert
    settings.trusted_proxy = "testclient"
    assert client.get("/api/health").json()["status"] == "ok"


def test_first_user_admin_others_need_grant(client):
    assert client.get("/api/me", headers=H1).json()["role"] == "admin"
    assert client.get("/api/me", headers=H2).json()["role"] == "none"
    assert client.get("/api/documents", headers=H2).status_code == 403
    uid = db.one("SELECT id FROM users WHERE ha_user_id='ha-other'")[0]
    assert client.patch(f"/api/users/{uid}", json={"role": "viewer"}, headers=H1).status_code == 200
    assert client.get("/api/documents", headers=H2).status_code == 200
    assert client.post("/api/documents/upload", files={"files": ("a.pdf", b"%PDF")}, headers=H2).status_code == 403
    assert client.get("/api/settings", headers=H2).status_code == 403


def test_csrf_header_required(client):
    client.get("/api/me", headers=H1)
    h = {k: v for k, v in H1.items() if k != "X-Requested-With"}
    assert client.post("/api/processing/pause", headers=h).status_code == 403
    assert client.post("/api/processing/pause", headers=H1).json() == {"paused": True}


def test_upload_and_visibility(client):
    client.get("/api/me", headers=H1)
    pdf = synth.text_pdf(synth.DOCS["rechnung"])
    r = client.post("/api/documents/upload", files=[("files", ("r.pdf", pdf, "application/pdf"))], headers=H1).json()
    doc_id = r["results"][0]["document_id"]
    assert r["results"][0]["status"] == "created"
    db.execute("UPDATE documents SET visibility='admins' WHERE id=?", (doc_id,))
    client.get("/api/me", headers=H2)
    db.execute("UPDATE users SET role='viewer' WHERE ha_user_id='ha-other'")
    assert client.get(f"/api/documents/{doc_id}", headers=H2).status_code == 404  # kein IDOR
    assert client.get(f"/api/documents/{doc_id}/file", headers=H2).status_code == 404
    assert client.get("/api/documents", headers=H2).json()["total"] == 0
    f = client.get(f"/api/documents/{doc_id}/file", headers=H1)
    assert f.status_code == 200 and f.content == pdf and "sandbox" in f.headers["content-security-policy"]


def test_auto_mode_requires_test_run(client):
    client.get("/api/me", headers=H1)
    r = client.patch("/api/settings", json={"processing_mode": "auto"}, headers=H1)
    assert r.status_code == 409
    assert client.patch("/api/settings", json={"processing_mode": "review"}, headers=H1).status_code == 200
    assert client.patch("/api/settings", json={"test_run_ok": True}, headers=H1).status_code == 400


def test_rules_api_validation_and_test(client):
    client.get("/api/me", headers=H1)
    bad = {"name": "x", "conditions": {"field": "text", "op": "regex", "value": "("}, "actions": {"review": True}}
    assert client.post("/api/rules", json=bad, headers=H1).status_code == 400
    ok = {"name": "x", "conditions": {"field": "filename", "op": "contains", "value": "rechnung"}, "actions": {"tags": ["a"]}}
    assert client.post("/api/rules", json=ok, headers=H1).status_code == 200
    r = client.post("/api/rules/test", json={**ok, "sample": {"filename": "Rechnung.pdf"}}, headers=H1).json()
    assert r["matches"][0]["matched"]


def test_ingress_base_path_injected(client, tmp_path, monkeypatch):
    from lorzdms.api import app as appmod

    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("<html><head><title>x</title></head><body></body></html>")
    monkeypatch.setattr(appmod, "STATIC_DIR", static)
    c = TestClient(create_app(init=False))
    html = c.get("/", headers={"X-Ingress-Path": "/api/hassio_ingress/abc123"}).text
    assert '<base href="/api/hassio_ingress/abc123/">' in html
    html = c.get("/", headers={"X-Ingress-Path": '/x"><script>'}).text
    assert "<script>" not in html.split("<title>")[0]


def test_google_client_upload_validation(client):
    client.get("/api/me", headers=H1)
    r = client.post("/api/google/client", files={"file": ("c.json", b'{"type":"service_account"}')}, headers=H1)
    assert r.status_code == 400 and "Dienstkonto" in r.json()["detail"]
    good = b'{"installed":{"client_id":"1-a.apps.googleusercontent.com","client_secret":"s","redirect_uris":["http://localhost"]}}'
    r = client.post("/api/google/client", files={"file": ("c.json", good)}, headers=H1)
    assert r.status_code == 200 and r.json()["client_type"] == "installed"
    st = client.get("/api/google/status", headers=H1).json()
    assert "client_secret" not in str(st)


def test_page_preview_png(client):
    client.get("/api/me", headers=H1)
    pdf = synth.text_pdf(synth.DOCS["rechnung"])
    doc_id = client.post("/api/documents/upload", files=[("files", ("r.pdf", pdf, "application/pdf"))], headers=H1).json()["results"][0]["document_id"]
    from tests.conftest import drain
    drain()
    r = client.get(f"/api/documents/{doc_id}/pages/1.png?width=400", headers=H1)
    assert r.status_code == 200 and r.content.startswith(b"\x89PNG")
    assert client.get(f"/api/documents/{doc_id}/pages/5.png", headers=H1).status_code == 404

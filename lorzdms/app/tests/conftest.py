from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lorzdms import appsettings, bootstrap, crypto, db  # noqa: E402
from lorzdms.config import Settings, set_settings  # noqa: E402
from lorzdms.devtools.fake_google import FakeGoogle  # noqa: E402
from lorzdms.google import http as ghttp  # noqa: E402
from lorzdms.google import oauth  # noqa: E402


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    s = Settings(data_dir=tmp_path / "data", share_dir=tmp_path / "share" / "lorzdms", trusted_proxy="testclient")
    s.scan_interval_seconds = 1
    set_settings(s)
    bootstrap.init(role="web")
    yield s
    db.close()


@pytest.fixture()
def fake(settings) -> FakeGoogle:
    fg = FakeGoogle()
    ghttp.set_transport(fg.transport())
    ghttp.set_sleep(lambda _s: None)
    yield fg
    ghttp.set_transport(None)


@pytest.fixture()
def account(fake) -> int:
    """Verbundenes Google-Konto (Token direkt hinterlegt) + Ordnerstruktur."""
    oauth.save_client({"client_type": "installed", "client_id": "x.apps.googleusercontent.com", "client_secret": "s", "redirect_uris": []})
    now = db.utcnow()
    cur = db.execute(
        "INSERT INTO google_accounts(email, scopes, status, created_at, updated_at) VALUES (?,?,?,?,?)",
        ("test@example.org", fake.granted_scopes, "connected", now, now),
    )
    acc = cur.lastrowid
    crypto.put_secret(f"google_token:{acc}", {"access_token": "at", "refresh_token": "rt", "expires_at": "2999-01-01T00:00:00+00:00"})
    return acc


@pytest.fixture()
def tree(fake, account):
    """Dokumente/00_Eingang, Dokumente/01_Manuelle_Pruefung, Dokumente/Nebengewerbe/Hosting …"""
    root = fake.add_folder("Dokumente")
    ids = {
        "root": root,
        "inbox": fake.add_folder("00_Eingang", root),
        "review": fake.add_folder("01_Manuelle_Pruefung", root),
        "privat": fake.add_folder("Privat", root),
        "neben": fake.add_folder("Nebengewerbe", root),
        "outside": fake.add_folder("Fremder Ordner"),
    }
    ids["hosting"] = fake.add_folder("Hosting", ids["neben"])
    ids["steuern"] = fake.add_folder("Steuern", ids["privat"])
    ids["vers"] = fake.add_folder("Versicherungen", ids["privat"])
    rows = [
        (root, "Dokumente", "Dokumente", "archive_root"),
        (ids["inbox"], "00_Eingang", "Dokumente/00_Eingang", "inbox"),
        (ids["review"], "01_Manuelle_Pruefung", "Dokumente/01_Manuelle_Pruefung", "review"),
        (ids["hosting"], "Hosting", "Dokumente/Nebengewerbe/Hosting", "archive"),
        (ids["steuern"], "Steuern", "Dokumente/Privat/Steuern", "archive"),
        (ids["vers"], "Versicherungen", "Dokumente/Privat/Versicherungen", "archive"),
    ]
    for drive_id, name, path, role in rows:
        db.execute("INSERT INTO drive_folders(account_id, drive_id, name, path, role) VALUES (?,?,?,?,?)",
                   (account, drive_id, name, path, role))
    return ids


def add_rule(name: str, conditions: dict, actions: dict, priority: int = 100) -> int:
    now = db.utcnow()
    return db.execute(
        "INSERT INTO rules(name, priority, enabled, conditions, actions, stop_processing, created_at, updated_at) VALUES (?,?,1,?,?,1,?,?)",
        (name, priority, json.dumps(conditions), json.dumps(actions), now, now),
    ).lastrowid


def enable_auto() -> None:
    appsettings.set("test_run_ok", True)
    appsettings.set("processing_mode", "auto")
    appsettings.set("setup_completed", True)


def drain(max_jobs: int = 50) -> int:
    from lorzdms import worker

    n = 0
    while n < max_jobs and worker.run_one("test-worker"):
        n += 1
    return n

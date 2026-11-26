"""Zugriff auf Google-Clients pro Konto inkl. Schreibschutz aus der Ordnerfreigabe."""

from __future__ import annotations

from . import db
from .google import oauth
from .google.drive import DriveClient, DriveGuard
from .google.gmail import GmailClient


def drive(account_id: int) -> DriveClient:
    return DriveClient(lambda: oauth.access_token(account_id))


def gmail(account_id: int) -> GmailClient:
    return GmailClient(lambda: oauth.access_token(account_id))


def guard(account_id: int) -> DriveGuard:
    rows = db.query("SELECT drive_id, role FROM drive_folders WHERE account_id=?", (account_id,))
    writable = {r["drive_id"] for r in rows if r["role"] in ("archive_root", "archive", "review")}
    inbox = {r["drive_id"] for r in rows if r["role"] == "inbox"}
    return DriveGuard(drive(account_id), writable, inbox)


def archive_folders() -> list[dict]:
    """Für Klassifizierung verfügbare Zielordner (alle Konten)."""
    rows = db.query(
        "SELECT account_id, drive_id, name, path, description FROM drive_folders WHERE role IN ('archive','archive_root') ORDER BY path"
    )
    return [dict(r) for r in rows]


def review_folder(account_id: int) -> str | None:
    row = db.one("SELECT drive_id FROM drive_folders WHERE account_id=? AND role='review' LIMIT 1", (account_id,))
    return row["drive_id"] if row else None


def folder_account(drive_id: str) -> int | None:
    row = db.one("SELECT account_id FROM drive_folders WHERE drive_id=? AND role IN ('archive','archive_root','review')", (drive_id,))
    return row["account_id"] if row else None

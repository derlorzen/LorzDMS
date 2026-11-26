"""Authentifizierung und Berechtigungen.

Ingress: Der Home Assistant Supervisor setzt ``X-Remote-User-Id`` usw. Diese Header
werden nur akzeptiert, wenn die TCP-Verbindung vom Supervisor-Proxy kommt. Andere
Verbindungen erhalten 401. Rollen: viewer < editor < admin. Der erste Benutzer wird
Administrator (die Seitenleiste ist per ``panel_admin`` auf HA-Administratoren begrenzt);
alle weiteren haben ohne Freigabe keinen Zugriff.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request

from .. import db
from ..config import get_settings

ROLE_ORDER = {"none": 0, "viewer": 1, "editor": 2, "admin": 3}
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


@dataclass
class User:
    id: int
    ha_user_id: str
    name: str
    display_name: str | None
    role: str

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    def can(self, role: str) -> bool:
        return ROLE_ORDER[self.role] >= ROLE_ORDER[role]


def _identity(request: Request) -> tuple[str, str, str | None] | None:
    s = get_settings()
    host = request.client.host if request.client else ""
    if s.dev_user and host in ("127.0.0.1", "::1", "testclient"):
        return f"dev:{s.dev_user}", s.dev_user, s.dev_user
    if host == s.trusted_proxy:
        uid = request.headers.get("x-remote-user-id")
        if uid:
            return uid, request.headers.get("x-remote-user-name") or uid, request.headers.get("x-remote-user-display-name")
    return None


def current_user(request: Request) -> User:
    ident = _identity(request)
    if ident is None:
        raise HTTPException(401, "Nicht angemeldet (Zugriff nur über Home Assistant Ingress)")
    if request.method not in SAFE_METHODS and request.headers.get("x-requested-with") != "lorzdms":
        raise HTTPException(403, "CSRF-Schutz: Header X-Requested-With fehlt")
    ha_id, name, display = ident
    row = db.one("SELECT * FROM users WHERE ha_user_id=?", (ha_id,))
    now = db.utcnow()
    if row is None:
        first = db.one("SELECT COUNT(*) n FROM users WHERE role='admin'")["n"] == 0
        role = "admin" if first else "none"
        db.execute(
            "INSERT INTO users(ha_user_id, name, display_name, role, created_at, last_seen_at) VALUES (?,?,?,?,?,?)",
            (ha_id, name, display, role, now, now),
        )
        row = db.one("SELECT * FROM users WHERE ha_user_id=?", (ha_id,))
        db.audit("user.created", row["id"], f"user:{row['id']}", role=role)
    elif not row["last_seen_at"] or row["last_seen_at"][:16] != now[:16]:
        db.execute("UPDATE users SET last_seen_at=?, name=?, display_name=? WHERE id=?", (now, name, display, row["id"]))
    if not row["active"]:
        raise HTTPException(403, "Benutzer deaktiviert")
    return User(row["id"], row["ha_user_id"], row["name"], row["display_name"], row["role"])


def require(role: str):
    def dep(user: User = Depends(current_user)) -> User:
        if not user.can(role):
            raise HTTPException(403, "Keine Berechtigung" if user.role != "none" else "Zugriff noch nicht freigegeben – bitte einen LorzDMS-Administrator fragen")
        return user

    return dep


def visible_clause(user: User, alias: str = "d") -> str:
    return "1=1" if user.is_admin else f"{alias}.visibility='members'"

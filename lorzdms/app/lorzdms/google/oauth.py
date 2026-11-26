"""Google OAuth 2.0 (Authorization Code + PKCE S256).

Ohne öffentlich erreichbare Oberfläche: Standard-Redirect ist eine Loopback-Adresse
(``http://127.0.0.1:8765/oauth2callback``). Google leitet den Browser nach der Zustimmung
dorthin; die Seite lädt nicht, aber die Adresszeile enthält ``code`` und ``state``. Diese
Adresse wird in LorzDMS eingefügt. Für Desktop-Clients („installed“) akzeptiert Google
jeden Loopback-Port ohne Registrierung; für Web-Clients muss die Adresse in der Cloud
Console als autorisierte Weiterleitungs-URI eingetragen sein.

Alternativ kann eine stabile HTTPS-Callback-URL genutzt werden (``/oauth/callback``).
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlencode, urlparse

from .. import crypto, db
from . import http

AUTH_URI = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URI = "https://oauth2.googleapis.com/token"
USERINFO_URI = "https://openidconnect.googleapis.com/v1/userinfo"
REVOKE_URI = "https://oauth2.googleapis.com/revoke"

SCOPE_DRIVE_FULL = "https://www.googleapis.com/auth/drive"
SCOPE_DRIVE_FILE = "https://www.googleapis.com/auth/drive.file"
SCOPE_GMAIL_READONLY = "https://www.googleapis.com/auth/gmail.readonly"
BASE_SCOPES = ["openid", "email"]
# Nur lesende Gmail-Berechtigung ist zulässig.
FORBIDDEN_SCOPES = {
    "https://mail.google.com/",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.insert",
    "https://www.googleapis.com/auth/gmail.labels",
}

CLIENT_SECRET_KEY = "google_client"


class OAuthConfigError(ValueError):
    pass


def parse_client_json(raw: str | bytes) -> dict:
    """Prüft eine heruntergeladene OAuth-Client-JSON und gibt die normalisierte Form zurück."""
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise OAuthConfigError("Die Datei ist kein gültiges JSON.") from exc
    if not isinstance(data, dict):
        raise OAuthConfigError("Unerwartetes Format.")
    if data.get("type") == "service_account":
        raise OAuthConfigError(
            "Das ist ein Dienstkonto-Schlüssel. Benötigt wird ein OAuth-Client (Typ Desktop-App oder Webanwendung)."
        )
    kind = "installed" if "installed" in data else "web" if "web" in data else None
    if kind is None:
        raise OAuthConfigError("Weder 'installed' (Desktop-App) noch 'web' (Webanwendung) gefunden.")
    inner = data[kind]
    missing = [k for k in ("client_id", "client_secret") if not inner.get(k)]
    if missing:
        raise OAuthConfigError(f"Fehlende Felder: {', '.join(missing)}")
    if not str(inner["client_id"]).endswith(".apps.googleusercontent.com"):
        raise OAuthConfigError("client_id sieht nicht nach einer Google-OAuth-Client-ID aus.")
    return {
        "client_type": kind,
        "client_id": inner["client_id"],
        "client_secret": inner["client_secret"],
        "project_id": inner.get("project_id"),
        "redirect_uris": inner.get("redirect_uris", []),
    }


def manual_client(client_id: str, client_secret: str, client_type: str = "installed") -> dict:
    payload = {client_type: {"client_id": client_id.strip(), "client_secret": client_secret.strip()}}
    return parse_client_json(json.dumps(payload))


def save_client(cfg: dict) -> None:
    crypto.put_secret(CLIENT_SECRET_KEY, cfg)


def load_client() -> dict | None:
    return crypto.get_secret(CLIENT_SECRET_KEY)


def redirect_uri_problems(cfg: dict, redirect_uri: str) -> list[str]:
    problems = []
    parsed = urlparse(redirect_uri)
    loopback = parsed.hostname in ("127.0.0.1", "localhost", "[::1]", "::1")
    if parsed.scheme not in ("http", "https"):
        problems.append("Redirect-URI muss http(s) sein.")
    if parsed.scheme == "http" and not loopback:
        problems.append("Nicht-Loopback-Redirects müssen HTTPS verwenden.")
    if cfg["client_type"] == "web" and redirect_uri not in cfg.get("redirect_uris", []):
        problems.append(
            f"Für Web-Clients muss '{redirect_uri}' in der Google Cloud Console als autorisierte Weiterleitungs-URI eingetragen sein."
        )
    return problems


def scopes_for(drive_mode: str, gmail: bool) -> list[str]:
    scopes = list(BASE_SCOPES)
    scopes.append(SCOPE_DRIVE_FULL if drive_mode == "full" else SCOPE_DRIVE_FILE)
    if gmail:
        scopes.append(SCOPE_GMAIL_READONLY)
    assert not FORBIDDEN_SCOPES & set(scopes)
    return scopes


def _pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)[:96]
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def start_authorization(redirect_uri: str, scopes: list[str], user_id: int | None) -> str:
    cfg = load_client()
    if not cfg:
        raise OAuthConfigError("Kein OAuth-Client hinterlegt.")
    if FORBIDDEN_SCOPES & set(scopes):
        raise OAuthConfigError("Schreibende Gmail-Berechtigungen sind nicht erlaubt.")
    state = secrets.token_urlsafe(32)
    verifier, challenge = _pkce()
    expires = datetime.now(timezone.utc) + timedelta(minutes=15)
    db.execute("DELETE FROM oauth_states WHERE expires_at < ?", (db.utcnow(),))
    db.execute(
        "INSERT INTO oauth_states(state, code_verifier, redirect_uri, scopes, created_by, expires_at) VALUES (?,?,?,?,?,?)",
        (state, crypto.encrypt(verifier.encode()).decode(), redirect_uri, json.dumps(scopes), user_id, expires.isoformat(timespec="seconds")),
    )
    params = {
        "client_id": cfg["client_id"],
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(scopes),
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "false",
    }
    return f"{AUTH_URI}?{urlencode(params)}"


def parse_redirect(pasted: str) -> tuple[str, str]:
    """Aus der eingefügten Adresszeile ``code`` und ``state`` lesen."""
    pasted = pasted.strip()
    qs = parse_qs(urlparse(pasted).query) if "?" in pasted else parse_qs(pasted)
    if "error" in qs:
        raise OAuthConfigError(f"Google meldet: {qs['error'][0]}")
    code, state = qs.get("code", [None])[0], qs.get("state", [None])[0]
    if not code or not state:
        raise OAuthConfigError("In der eingefügten Adresse fehlen 'code' oder 'state'.")
    return code, state


def complete_authorization(code: str, state: str) -> dict:
    row = db.one("SELECT * FROM oauth_states WHERE state=?", (state,))
    if row is None:
        raise OAuthConfigError("Unbekannter oder bereits verwendeter Autorisierungsvorgang.")
    db.execute("DELETE FROM oauth_states WHERE state=?", (state,))
    if row["expires_at"] < db.utcnow():
        raise OAuthConfigError("Der Autorisierungsvorgang ist abgelaufen. Bitte neu starten.")
    cfg = load_client()
    verifier = crypto.decrypt(row["code_verifier"].encode()).decode()
    resp = http.request(
        "POST",
        TOKEN_URI,
        retries=2,
        data={
            "code": code,
            "client_id": cfg["client_id"],
            "client_secret": cfg["client_secret"],
            "redirect_uri": row["redirect_uri"],
            "grant_type": "authorization_code",
            "code_verifier": verifier,
        },
    )
    tok = resp.json()
    if "refresh_token" not in tok:
        raise OAuthConfigError(
            "Google hat kein Refresh-Token geliefert. Zugriff unter myaccount.google.com/permissions entfernen und erneut verbinden."
        )
    granted = set(tok.get("scope", "").split())
    requested = set(json.loads(row["scopes"]))
    if FORBIDDEN_SCOPES & granted:
        raise OAuthConfigError("Google hat unerwartet schreibende Gmail-Rechte erteilt; Verbindung abgelehnt.")
    info = http.request("GET", USERINFO_URI, headers={"Authorization": f"Bearer {tok['access_token']}"}).json()
    email = info.get("email")
    if not email:
        raise OAuthConfigError("E-Mail-Adresse des Kontos konnte nicht ermittelt werden.")
    now = db.utcnow()
    db.execute(
        "INSERT INTO google_accounts(email, scopes, status, created_at, updated_at) VALUES (?,?,?,?,?) "
        "ON CONFLICT(email) DO UPDATE SET scopes=excluded.scopes, status='connected', last_error=NULL, updated_at=excluded.updated_at",
        (email, " ".join(sorted(granted or requested)), "connected", now, now),
    )
    account = db.one("SELECT * FROM google_accounts WHERE email=?", (email,))
    _store_token(account["id"], tok)
    db.audit("google.connect", row["created_by"], target=f"account:{account['id']}", scopes=sorted(granted))
    missing = sorted(requested - granted - {"openid", "email"})
    return {"account_id": account["id"], "email": email, "missing_scopes": missing}


def _store_token(account_id: int, tok: dict) -> None:
    existing = crypto.get_secret(f"google_token:{account_id}") or {}
    expires = datetime.now(timezone.utc) + timedelta(seconds=int(tok.get("expires_in", 3600)) - 60)
    crypto.put_secret(
        f"google_token:{account_id}",
        {
            "access_token": tok["access_token"],
            "refresh_token": tok.get("refresh_token") or existing.get("refresh_token"),
            "expires_at": expires.isoformat(timespec="seconds"),
        },
    )


def access_token(account_id: int) -> str:
    tok = crypto.get_secret(f"google_token:{account_id}")
    if not tok:
        raise http.AuthExpired(401, "Kein Token gespeichert", "no_token")
    if tok["expires_at"] > datetime.now(timezone.utc).isoformat(timespec="seconds"):
        return tok["access_token"]
    cfg = load_client()
    try:
        resp = http.request(
            "POST",
            TOKEN_URI,
            retries=3,
            data={
                "client_id": cfg["client_id"],
                "client_secret": cfg["client_secret"],
                "refresh_token": tok["refresh_token"],
                "grant_type": "refresh_token",
            },
        )
    except http.AuthExpired as exc:
        db.execute(
            "UPDATE google_accounts SET status='reauth_required', last_error=?, updated_at=? WHERE id=?",
            ("Refresh-Token abgelaufen oder widerrufen (im Google-Testmodus nach 7 Tagen)", db.utcnow(), account_id),
        )
        raise exc
    _store_token(account_id, resp.json())
    db.execute("UPDATE google_accounts SET status='connected', last_error=NULL, updated_at=? WHERE id=?", (db.utcnow(), account_id))
    return resp.json()["access_token"]


def has_scope(account_id: int, scope: str) -> bool:
    row = db.one("SELECT scopes FROM google_accounts WHERE id=?", (account_id,))
    return bool(row) and scope in row["scopes"].split()

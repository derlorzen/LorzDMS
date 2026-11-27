"""Benachrichtigungen über Home Assistant (Supervisor-Proxy zur Core-API).

Es werden nur Titel und Fälligkeit einer Frist übertragen, keine Dokumentinhalte.
Benötigt ``homeassistant_api: true`` in der App-Konfiguration; der Supervisor stellt dann
``SUPERVISOR_TOKEN`` bereit.
"""

from __future__ import annotations

import os
import re

import httpx

from . import appsettings

SERVICE_RE = re.compile(r"^(persistent_notification\.create|notify\.[a-z0-9_]{1,64})$")
CORE_API = "http://supervisor/core/api"


class NotifyError(RuntimeError):
    pass


def validate_service(service: str) -> str:
    if not isinstance(service, str) or not SERVICE_RE.match(service):
        raise ValueError("Dienst muss persistent_notification.create oder notify.<name> sein")
    return service


def available() -> bool:
    return bool(os.environ.get("SUPERVISOR_TOKEN"))


def send(title: str, message: str, tag: str, *, service: str | None = None, transport: httpx.BaseTransport | None = None) -> None:
    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        raise NotifyError("Keine Verbindung zu Home Assistant (SUPERVISOR_TOKEN fehlt)")
    service = validate_service(service or appsettings.get("notify_service") or "persistent_notification.create")
    domain, name = service.split(".", 1)
    if domain == "persistent_notification":
        payload = {"title": title, "message": message, "notification_id": tag}
    else:
        payload = {"title": title, "message": message, "data": {"tag": tag, "group": "lorzdms"}}
    with httpx.Client(timeout=15, transport=transport) as client:
        r = client.post(f"{CORE_API}/services/{domain}/{name}", json=payload, headers={"Authorization": f"Bearer {token}"})
    if r.status_code >= 400:
        raise NotifyError(f"Home Assistant antwortet mit HTTP {r.status_code} für {service}")

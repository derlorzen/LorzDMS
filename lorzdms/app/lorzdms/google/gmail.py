"""Gmail-API – ausschließlich lesend.

Diese Klasse enthält bewusst keine Methoden, die Nachrichten verändern (modify, trash,
delete, labels, send). Der Test ``test_gmail_readonly`` prüft, dass nur GET-Anfragen
gestellt werden.
"""

from __future__ import annotations

import base64
import re
from email.utils import parseaddr, parsedate_to_datetime
from typing import Callable, Iterable

from . import http

API = "https://gmail.googleapis.com/gmail/v1/users/me"

DEFAULT_EXTENSIONS = (".pdf",)
OPTIONAL_EXTENSIONS = (".jpg", ".jpeg", ".png", ".tif", ".tiff")
MIN_IMAGE_BYTES = 30_000  # kleinere Bilder sind meist Logos/Signaturen/Tracking-Pixel
_TRACKING = re.compile(r"(logo|signature|signatur|banner|spacer|pixel|facebook|twitter|linkedin|instagram)", re.I)


class GmailClient:
    def __init__(self, token_provider: Callable[[], str]):
        self._token = token_provider

    def _get(self, path: str, params: dict | None = None) -> dict:
        return http.request("GET", f"{API}{path}", headers={"Authorization": f"Bearer {self._token()}"}, params=params or {}).json()

    def profile(self) -> dict:
        return self._get("/profile")

    def list_labels(self) -> list[dict]:
        return self._get("/labels").get("labels", [])

    def search(self, query: str, label_ids: list[str] | None = None, limit: int = 500) -> Iterable[str]:
        token, n = None, 0
        while True:
            params: dict = {"q": query, "maxResults": "100"}
            if label_ids:
                params["labelIds"] = label_ids
            if token:
                params["pageToken"] = token
            data = self._get("/messages", params)
            for m in data.get("messages", []):
                yield m["id"]
                n += 1
                if n >= limit:
                    return
            token = data.get("nextPageToken")
            if not token:
                return

    def history(self, start_history_id: str, label_id: str | None = None) -> tuple[list[str], str]:
        """Neue Nachrichten seit ``start_history_id``. Wirft ``GoogleApiError(404)``, wenn
        die History-ID zu alt ist (dann Vollabgleich über :meth:`search`)."""
        ids: list[str] = []
        token = None
        latest = start_history_id
        while True:
            params: dict = {"startHistoryId": start_history_id, "historyTypes": "messageAdded", "maxResults": "500"}
            if label_id:
                params["labelId"] = label_id
            if token:
                params["pageToken"] = token
            data = self._get("/history", params)
            for h in data.get("history", []):
                for added in h.get("messagesAdded", []):
                    mid = added["message"]["id"]
                    if mid not in ids:
                        ids.append(mid)
            latest = data.get("historyId", latest)
            token = data.get("nextPageToken")
            if not token:
                return ids, latest

    def message(self, message_id: str) -> dict:
        return self._get(f"/messages/{message_id}", {"format": "full"})

    def attachment(self, message_id: str, attachment_id: str) -> bytes:
        data = self._get(f"/messages/{message_id}/attachments/{attachment_id}")
        return base64.urlsafe_b64decode(data["data"] + "=" * (-len(data["data"]) % 4))


def _headers(payload: dict) -> dict[str, str]:
    return {h["name"].lower(): h["value"] for h in payload.get("headers", [])}


def _walk(part: dict) -> Iterable[dict]:
    yield part
    for p in part.get("parts", []) or []:
        yield from _walk(p)


def _body_text(payload: dict, limit: int = 20_000) -> str:
    for p in _walk(payload):
        if p.get("mimeType") == "text/plain" and p.get("body", {}).get("data"):
            raw = p["body"]["data"]
            return base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)).decode("utf-8", "replace")[:limit]
    return ""


def message_meta(msg: dict) -> dict:
    payload = msg.get("payload", {})
    h = _headers(payload)
    name, email = parseaddr(h.get("from", ""))
    try:
        received = parsedate_to_datetime(h["date"]).isoformat() if h.get("date") else None
    except (TypeError, ValueError):
        received = None
    return {
        "gmail_message_id": msg["id"],
        "thread_id": msg.get("threadId"),
        "rfc_message_id": h.get("message-id"),
        "from_name": name or None,
        "from_email": email.lower() or None,
        "to": h.get("to"),
        "subject": h.get("subject"),
        "received_at": received,
        "label_ids": msg.get("labelIds", []),
        "body_excerpt": _body_text(payload, 4000),
    }


def attachments(msg: dict, extensions: tuple[str, ...] = DEFAULT_EXTENSIONS) -> list[dict]:
    """Relevante Anhänge einer Nachricht. Inline-Grafiken, Logos und kleine Bilder werden
    ausgeschlossen. ``part_id`` ist stabil; die Gmail-``attachmentId`` kann sich zwischen
    Abrufen ändern und wird daher nicht als Schlüssel verwendet."""
    out = []
    for part in _walk(msg.get("payload", {})):
        filename = part.get("filename") or ""
        body = part.get("body", {})
        if not filename or not body.get("attachmentId"):
            continue
        lower = filename.lower()
        if not lower.endswith(tuple(extensions)):
            continue
        h = _headers(part)
        disposition = h.get("content-disposition", "").lower()
        is_image = part.get("mimeType", "").startswith("image/")
        if is_image:
            if disposition.startswith("inline") or "content-id" in h:
                continue
            if int(body.get("size", 0)) < MIN_IMAGE_BYTES or _TRACKING.search(filename):
                continue
        out.append({
            "part_id": part.get("partId", ""),
            "attachment_id": body["attachmentId"],
            "filename": filename,
            "mime_type": part.get("mimeType"),
            "size": int(body.get("size", 0)),
        })
    return out

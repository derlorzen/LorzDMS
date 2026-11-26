"""In-Memory-Nachbildung der genutzten Google-APIs (Drive v3, Gmail v1, OAuth) für Tests
und den Demo-Modus. Wird als ``httpx.MockTransport`` eingehängt, sodass der echte
Client-Code (URLs, Parameter, Fehlerbehandlung) ausgeführt wird.

Fehlerinjektion: ``fake.faults.append((predicate, action))`` – ``action`` ist ein Status-
code (int) oder eine Exception, die beim nächsten passenden Request ausgelöst wird.
"""

from __future__ import annotations

import base64
import hashlib
import itertools
import json
import re
from dataclasses import dataclass, field
from typing import Callable
from urllib.parse import parse_qs, urlparse

import httpx

FOLDER = "application/vnd.google-apps.folder"


@dataclass
class FakeFile:
    id: str
    name: str
    mimeType: str
    parents: list[str]
    content: bytes = b""
    appProperties: dict = field(default_factory=dict)
    trashed: bool = False

    def meta(self) -> dict:
        d = {
            "id": self.id, "name": self.name, "mimeType": self.mimeType, "parents": list(self.parents),
            "trashed": self.trashed, "appProperties": dict(self.appProperties),
            "webViewLink": f"https://drive.google.com/file/d/{self.id}/view",
        }
        if self.mimeType != FOLDER:
            d["size"] = str(len(self.content))
            d["md5Checksum"] = hashlib.md5(self.content).hexdigest()  # noqa: S324
        return d


class FakeGoogle:
    def __init__(self, email: str = "test@example.org"):
        self.email = email
        self.files: dict[str, FakeFile] = {"root": FakeFile("root", "Meine Ablage", FOLDER, [])}
        self.messages: dict[str, dict] = {}
        self.attachments: dict[tuple[str, str], bytes] = {}
        self.history_id = 1000
        self.history: list[tuple[int, str]] = []
        self.requests: list[tuple[str, str]] = []
        self.faults: list[tuple[Callable[[httpx.Request], bool], object]] = []
        self._ids = itertools.count(1)
        self._uploads: dict[str, dict] = {}
        self.refresh_valid = True
        self.granted_scopes = "openid https://www.googleapis.com/auth/userinfo.email https://www.googleapis.com/auth/drive https://www.googleapis.com/auth/gmail.readonly"

    # Testdaten ----------------------------------------------------------------
    def new_id(self, prefix: str = "f") -> str:
        return f"{prefix}{next(self._ids):05d}"

    def add_folder(self, name: str, parent: str = "root") -> str:
        fid = self.new_id("d")
        self.files[fid] = FakeFile(fid, name, FOLDER, [parent])
        return fid

    def add_file(self, name: str, content: bytes, parent: str, mime: str = "application/pdf") -> str:
        fid = self.new_id("f")
        self.files[fid] = FakeFile(fid, name, mime, [parent], content)
        return fid

    def add_message(self, *, sender: str, subject: str, attachments: list[tuple[str, bytes, str]],
                    labels: list[str] | None = None, inline_images: list[tuple[str, bytes]] | None = None) -> str:
        mid = self.new_id("m")
        parts = [{"partId": "0", "mimeType": "text/plain", "filename": "", "headers": [],
                  "body": {"size": 5, "data": base64.urlsafe_b64encode(b"Hallo").decode()}}]
        for i, (fname, data, mime) in enumerate(attachments, start=1):
            aid = f"att-{mid}-{i}-{len(self.attachments)}"
            self.attachments[(mid, aid)] = data
            parts.append({"partId": str(i), "mimeType": mime, "filename": fname,
                          "headers": [{"name": "Content-Disposition", "value": f'attachment; filename="{fname}"'}],
                          "body": {"attachmentId": aid, "size": len(data)}})
        for j, (fname, data) in enumerate(inline_images or [], start=len(parts)):
            aid = f"inl-{mid}-{j}"
            self.attachments[(mid, aid)] = data
            parts.append({"partId": str(j), "mimeType": "image/png", "filename": fname,
                          "headers": [{"name": "Content-Disposition", "value": "inline"}, {"name": "Content-ID", "value": "<x>"}],
                          "body": {"attachmentId": aid, "size": len(data)}})
        self.messages[mid] = {
            "id": mid, "threadId": mid, "labelIds": labels or ["INBOX"],
            "payload": {"mimeType": "multipart/mixed", "headers": [
                {"name": "From", "value": sender}, {"name": "Subject", "value": subject},
                {"name": "Date", "value": "Tue, 24 Nov 2026 10:00:00 +0100"}, {"name": "Message-ID", "value": f"<{mid}@example>"},
            ], "parts": parts},
        }
        self.history_id += 1
        self.history.append((self.history_id, mid))
        return mid

    # Transport ----------------------------------------------------------------
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append((request.method, str(request.url)))
        for i, (pred, action) in enumerate(self.faults):
            if pred(request):
                self.faults.pop(i)
                if isinstance(action, Exception):
                    raise action
                return httpx.Response(int(action), json={"error": {"code": action, "message": "injected"}})
        url = urlparse(str(request.url))
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        host, path = url.netloc, url.path
        if host == "oauth2.googleapis.com" and path == "/token":
            return self._token(request)
        if host == "openidconnect.googleapis.com":
            return httpx.Response(200, json={"email": self.email, "email_verified": True})
        if host == "www.googleapis.com" and path.startswith("/drive/v3"):
            return self._drive(request, path[len("/drive/v3"):], q)
        if host == "www.googleapis.com" and path.startswith("/upload/drive/v3"):
            return self._upload_init(request, q)
        if host == "upload.fake":
            return self._upload_put(request, path)
        if host == "gmail.googleapis.com":
            return self._gmail(request, path[len("/gmail/v1/users/me"):], q, url.query)
        return httpx.Response(404, json={"error": {"message": f"fake: unbekannt {host}{path}"}})

    def _token(self, request: httpx.Request) -> httpx.Response:
        form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
        if form.get("grant_type") == "authorization_code":
            if form.get("code") != "good-code" or not form.get("code_verifier"):
                return httpx.Response(400, json={"error": "invalid_grant", "error_description": "Bad code"})
            return httpx.Response(200, json={"access_token": "at-1", "refresh_token": "rt-1", "expires_in": 3600, "scope": self.granted_scopes})
        if form.get("grant_type") == "refresh_token":
            if not self.refresh_valid:
                return httpx.Response(400, json={"error": "invalid_grant", "error_description": "Token has been expired or revoked."})
            return httpx.Response(200, json={"access_token": "at-2", "expires_in": 3600, "scope": self.granted_scopes})
        return httpx.Response(400, json={"error": "unsupported_grant_type"})

    def _match(self, f: FakeFile, query: str) -> bool:
        for m in re.finditer(r"'([^']+)' in parents", query):
            if m.group(1) not in f.parents:
                return False
        if "trashed=false" in query and f.trashed:
            return False
        m = re.search(r"mimeType(!?=)'([^']+)'", query)
        if m:
            eq = f.mimeType == m.group(2)
            if (m.group(1) == "=") != eq:
                return False
        m = re.search(r"appProperties has \{ key='([^']+)' and value='([^']+)' \}", query)
        if m and f.appProperties.get(m.group(1)) != m.group(2):
            return False
        return True

    def _drive(self, request: httpx.Request, path: str, q: dict) -> httpx.Response:
        if path == "/about":
            return httpx.Response(200, json={"user": {"emailAddress": self.email}})
        if path == "/files" and request.method == "GET":
            found = [f.meta() for f in self.files.values() if f.id != "root" and self._match(f, q.get("q", ""))]
            return httpx.Response(200, json={"files": found})
        if path == "/files" and request.method == "POST":
            body = json.loads(request.content)
            fid = self.new_id("d")
            self.files[fid] = FakeFile(fid, body["name"], body["mimeType"], body["parents"])
            return httpx.Response(200, json=self.files[fid].meta())
        m = re.fullmatch(r"/files/([^/]+)", path)
        if not m:
            return httpx.Response(404, json={"error": {"message": "not found"}})
        f = self.files.get(m.group(1))
        if f is None:
            return httpx.Response(404, json={"error": {"message": "File not found", "errors": [{"reason": "notFound"}]}})
        if request.method == "GET":
            if q.get("alt") == "media":
                return httpx.Response(200, content=f.content)
            return httpx.Response(200, json=f.meta())
        if request.method == "PATCH":
            body = json.loads(request.content or b"{}")
            if "name" in body:
                f.name = body["name"]
            for p in filter(None, q.get("removeParents", "").split(",")):
                if p in f.parents:
                    f.parents.remove(p)
            for p in filter(None, q.get("addParents", "").split(",")):
                if p not in f.parents:
                    f.parents.append(p)
            if "trashed" in body:
                f.trashed = body["trashed"]
            return httpx.Response(200, json=f.meta())
        if request.method == "DELETE":
            del self.files[f.id]
            return httpx.Response(204)
        return httpx.Response(405)

    def _upload_init(self, request: httpx.Request, q: dict) -> httpx.Response:
        sid = f"s{len(self._uploads) + 1}"
        self._uploads[sid] = {"meta": json.loads(request.content), "mime": request.headers.get("x-upload-content-type")}
        return httpx.Response(200, headers={"Location": f"https://upload.fake/session/{sid}"})

    def _upload_put(self, request: httpx.Request, path: str) -> httpx.Response:
        sid = path.rsplit("/", 1)[-1]
        up = self._uploads.pop(sid, None)
        if up is None:
            return httpx.Response(404, json={"error": {"message": "session"}})
        meta = up["meta"]
        fid = self.new_id("f")
        self.files[fid] = FakeFile(fid, meta["name"], up["mime"], meta["parents"], request.content, meta.get("appProperties", {}))
        return httpx.Response(200, json=self.files[fid].meta())

    def _gmail(self, request: httpx.Request, path: str, q: dict, raw_query: str) -> httpx.Response:
        if request.method != "GET":
            return httpx.Response(403, json={"error": {"message": "fake: Gmail ist schreibgeschützt"}})
        if path == "/profile":
            return httpx.Response(200, json={"emailAddress": self.email, "historyId": str(self.history_id)})
        if path == "/labels":
            return httpx.Response(200, json={"labels": [{"id": "INBOX", "name": "INBOX"}, {"id": "Label_1", "name": "Rechnungen"}]})
        if path == "/messages":
            labels = parse_qs(raw_query).get("labelIds", [])
            ids = [{"id": m} for m, msg in self.messages.items() if not labels or set(labels) & set(msg["labelIds"])]
            return httpx.Response(200, json={"messages": ids})
        if path == "/history":
            start = int(q["startHistoryId"])
            if start < 900:
                return httpx.Response(404, json={"error": {"message": "Requested entity was not found."}})
            items = [{"id": str(h), "messagesAdded": [{"message": {"id": m}}]} for h, m in self.history if h > start]
            return httpx.Response(200, json={"history": items, "historyId": str(self.history_id)})
        m = re.fullmatch(r"/messages/([^/]+)/attachments/([^/]+)", path)
        if m:
            data = self.attachments.get((m.group(1), m.group(2)))
            if data is None:
                return httpx.Response(404, json={"error": {"message": "attachment"}})
            return httpx.Response(200, json={"data": base64.urlsafe_b64encode(data).decode().rstrip("="), "size": len(data)})
        m = re.fullmatch(r"/messages/([^/]+)", path)
        if m and m.group(1) in self.messages:
            return httpx.Response(200, json=self.messages[m.group(1)])
        return httpx.Response(404, json={"error": {"message": "not found"}})

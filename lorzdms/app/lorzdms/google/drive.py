"""Google Drive v3 über REST.

Sicherheitsprinzipien:
- Es gibt **keine** Lösch- oder Papierkorb-Methode.
- Jede Schreiboperation (Upload, Verschieben, Umbenennen, Ordner anlegen) läuft durch
  :class:`DriveGuard` und ist nur unterhalb freigegebener Archiv-/Prüfordner erlaubt.
  Verschieben aus einem freigegebenen Eingangsordner ist erlaubt.
- Verschieben erfolgt über ``addParents``/``removeParents``; die Datei-ID bleibt erhalten.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Callable, Iterable

from . import http

API = "https://www.googleapis.com/drive/v3"
UPLOAD_API = "https://www.googleapis.com/upload/drive/v3"
FOLDER_MIME = "application/vnd.google-apps.folder"
FILE_FIELDS = "id,name,mimeType,parents,size,md5Checksum,modifiedTime,trashed,webViewLink,appProperties,driveId"


class WriteNotAllowed(PermissionError):
    pass


def _q(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


class DriveClient:
    def __init__(self, token_provider: Callable[[], str]):
        self._token = token_provider

    def _h(self) -> dict:
        return {"Authorization": f"Bearer {self._token()}"}

    def _params(self, extra: dict | None = None) -> dict:
        p = {"supportsAllDrives": "true"}
        if extra:
            p.update(extra)
        return p

    # Lesen ---------------------------------------------------------------
    def get(self, file_id: str, fields: str = FILE_FIELDS) -> dict:
        return http.request("GET", f"{API}/files/{file_id}", headers=self._h(), params=self._params({"fields": fields})).json()

    def list(self, q: str, fields: str = FILE_FIELDS, page_size: int = 200) -> Iterable[dict]:
        token = None
        while True:
            params = self._params({
                "q": q,
                "fields": f"nextPageToken,files({fields})",
                "pageSize": str(page_size),
                "includeItemsFromAllDrives": "true",
                "corpora": "allDrives",
            })
            if token:
                params["pageToken"] = token
            data = http.request("GET", f"{API}/files", headers=self._h(), params=params).json()
            yield from data.get("files", [])
            token = data.get("nextPageToken")
            if not token:
                return

    def children(self, folder_id: str, folders_only: bool = False) -> list[dict]:
        q = f"'{_q(folder_id)}' in parents and trashed=false"
        if folders_only:
            q += f" and mimeType='{FOLDER_MIME}'"
        return list(self.list(q))

    def files_in(self, folder_id: str) -> list[dict]:
        q = f"'{_q(folder_id)}' in parents and trashed=false and mimeType!='{FOLDER_MIME}'"
        return list(self.list(q))

    def names_in(self, folder_id: str) -> set[str]:
        return {f["name"] for f in self.children(folder_id)}

    def find_by_app_property(self, folder_id: str, key: str, value: str) -> dict | None:
        q = (
            f"'{_q(folder_id)}' in parents and trashed=false and "
            f"appProperties has {{ key='{_q(key)}' and value='{_q(value)}' }}"
        )
        for f in self.list(q):
            return f
        return None

    def download(self, file_id: str, dest: Path, max_bytes: int) -> tuple[int, str]:
        """Lädt eine Datei herunter; Rückgabe (Größe, MD5). Bricht bei Überschreitung ab."""
        md5 = hashlib.md5()  # noqa: S324 – nur Vergleich mit Drive-Prüfsumme
        size = 0
        tmp = dest.with_suffix(dest.suffix + ".part")
        with http.client(timeout=300) as c:
            with c.stream("GET", f"{API}/files/{file_id}", headers=self._h(), params=self._params({"alt": "media"})) as resp:
                if resp.status_code >= 400:
                    resp.read()
                    raise http._error(resp)
                with tmp.open("wb") as fh:
                    for chunk in resp.iter_bytes(1024 * 256):
                        size += len(chunk)
                        if size > max_bytes:
                            fh.close()
                            tmp.unlink(missing_ok=True)
                            raise ValueError("Datei überschreitet das Größenlimit")
                        md5.update(chunk)
                        fh.write(chunk)
        tmp.replace(dest)
        return size, md5.hexdigest()

    def ancestors(self, file_id: str, limit: int = 40) -> list[str]:
        chain, current = [], file_id
        for _ in range(limit):
            meta = self.get(current, "id,parents")
            parents = meta.get("parents") or []
            if not parents:
                break
            current = parents[0]
            chain.append(current)
        return chain

    # Schreiben (nur über DriveGuard aufrufen) ------------------------------
    def _upload(self, local: Path, name: str, parent: str, mime: str, app_properties: dict) -> dict:
        meta = {"name": name, "parents": [parent], "appProperties": app_properties}
        init = http.request(
            "POST",
            f"{UPLOAD_API}/files",
            headers={**self._h(), "X-Upload-Content-Type": mime, "Content-Type": "application/json; charset=UTF-8"},
            params=self._params({"uploadType": "resumable", "fields": FILE_FIELDS}),
            content=json.dumps(meta).encode(),
        )
        location = init.headers.get("Location")
        if not location:
            raise http.GoogleApiError(500, "Keine Upload-URL erhalten")
        resp = http.request(
            "PUT", location, headers={**self._h(), "Content-Type": mime}, content=local.read_bytes(), retries=3
        )
        return resp.json()

    def _update(self, file_id: str, *, name: str | None, add: str | None, remove: list[str] | None) -> dict:
        params = self._params({"fields": FILE_FIELDS})
        if add:
            params["addParents"] = add
        if remove:
            params["removeParents"] = ",".join(remove)
        body = {"name": name} if name else {}
        return http.request(
            "PATCH", f"{API}/files/{file_id}", headers={**self._h(), "Content-Type": "application/json"},
            params=params, content=json.dumps(body).encode(),
        ).json()

    def _create_folder(self, name: str, parent: str) -> dict:
        return http.request(
            "POST", f"{API}/files", headers={**self._h(), "Content-Type": "application/json"},
            params=self._params({"fields": FILE_FIELDS}),
            content=json.dumps({"name": name, "mimeType": FOLDER_MIME, "parents": [parent]}).encode(),
        ).json()


class DriveGuard:
    """Erzwingt, dass Schreiboperationen nur in freigegebenen Bereichen stattfinden."""

    def __init__(self, client: DriveClient, writable_roots: set[str], inbox_roots: set[str]):
        self.client = client
        self.writable_roots = set(writable_roots)
        self.inbox_roots = set(inbox_roots)
        self._cache: dict[str, list[str]] = {}

    def _within(self, folder_id: str, roots: set[str]) -> bool:
        if not roots:
            return False
        if folder_id in roots:
            return True
        if folder_id not in self._cache:
            self._cache[folder_id] = self.client.ancestors(folder_id)
        return bool(roots & set(self._cache[folder_id]))

    def assert_writable(self, folder_id: str) -> None:
        # Eingangsordner sind nie Ablageziel, auch wenn sie unter dem Archiv liegen.
        if self._within(folder_id, self.inbox_roots) or not self._within(folder_id, self.writable_roots):
            raise WriteNotAllowed(f"Ordner {folder_id} liegt nicht in einem freigegebenen Archivordner")

    def upload(self, local: Path, name: str, parent: str, mime: str, app_properties: dict) -> dict:
        self.assert_writable(parent)
        return self.client._upload(local, name, parent, mime, app_properties)

    def move(self, file_id: str, new_parent: str, new_name: str | None) -> tuple[dict, list[str], str]:
        """Verschiebt eine Datei. Erlaubt nur, wenn die Datei in einem Eingangs- oder
        Archivbereich liegt und das Ziel beschreibbar ist. Rückgabe: (neue Metadaten,
        alte Eltern, alter Name) für die Rückgängig-Funktion."""
        self.assert_writable(new_parent)
        meta = self.client.get(file_id, "id,name,parents")
        old_parents = meta.get("parents") or []
        allowed_src = self.writable_roots | self.inbox_roots
        if not any(self._within(p, allowed_src) for p in old_parents):
            raise WriteNotAllowed("Quelldatei liegt außerhalb freigegebener Ordner")
        remove = [p for p in old_parents if p != new_parent]
        updated = self.client._update(file_id, name=new_name, add=new_parent if new_parent not in old_parents else None, remove=remove)
        return updated, old_parents, meta["name"]

    def restore(self, file_id: str, parents: list[str], name: str) -> dict:
        """Rückgängig: Datei zurück an ihren früheren Ort (muss freigegeben sein)."""
        allowed = self.writable_roots | self.inbox_roots
        for p in parents:
            if not self._within(p, allowed):
                raise WriteNotAllowed("Ursprungsordner ist nicht (mehr) freigegeben")
        meta = self.client.get(file_id, "id,parents")
        current = meta.get("parents") or []
        add = ",".join(p for p in parents if p not in current) or None
        remove = [p for p in current if p not in parents]
        return self.client._update(file_id, name=name, add=add, remove=remove)

    def ensure_folder(self, name: str, parent: str) -> dict:
        self.assert_writable(parent)
        for f in self.client.children(parent, folders_only=True):
            if f["name"] == name:
                return f
        return self.client._create_folder(name, parent)

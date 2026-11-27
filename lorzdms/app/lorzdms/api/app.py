"""FastAPI-Anwendung: REST-API unter ``/api`` und die gebaute Weboberfläche.

Die Oberfläche verwendet ausschließlich relative Pfade; der Ingress-Basispfad wird aus
``X-Ingress-Path`` als ``<base href>`` in ``index.html`` eingesetzt.
"""

from __future__ import annotations

import html
import json
import logging
import re
import shutil
from pathlib import Path
from typing import Any

from fastapi import Body, Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from pydantic import BaseModel, Field

from .. import __version__, actions, appsettings, bootstrap, crypto, db, jobqueue, services
from ..ai import providers as ai_providers, decider
from ..config import get_settings
from ..google import http as ghttp
from ..google import oauth
from ..google.drive import FOLDER_MIME
from ..pipeline import naming, rules, states, nvidia_ocr
from ..pipeline.processor import load
from ..pipeline.text import ocr_available
from ..sources import intake
from .deps import User, current_user, require, visible_clause

log = logging.getLogger("lorzdms.api")
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


def create_app(init: bool = True) -> FastAPI:
    if init:
        bootstrap.init(role="web")
    app = FastAPI(title="LorzDMS", version=__version__, docs_url="/api/docs", openapi_url="/api/openapi.json", redoc_url=None)

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; "
            "script-src 'self'; frame-src 'self' blob:; object-src 'self'; frame-ancestors 'self'; base-uri 'self'; form-action 'self'",
        )
        response.headers.setdefault("Cache-Control", "no-store") if request.url.path.startswith("/api") else None
        return response

    @app.exception_handler(actions.ActionError)
    async def action_error(_: Request, exc: actions.ActionError):
        return JSONResponse({"detail": str(exc), "code": "action_error"}, status_code=409)

    @app.exception_handler(ghttp.AuthExpired)
    async def auth_expired(_: Request, exc: ghttp.AuthExpired):
        return JSONResponse({"detail": "Google-Anmeldung abgelaufen – bitte Konto neu verbinden", "code": "google_reauth"}, status_code=409)

    @app.exception_handler(ghttp.GoogleApiError)
    async def google_error(_: Request, exc: ghttp.GoogleApiError):
        return JSONResponse({"detail": f"Google-API: {exc}", "code": "google_error"}, status_code=502)

    register_routes(app)
    return app


# Schemas ----------------------------------------------------------------------

class ApproveBody(BaseModel):
    folder_drive_id: str | None = None
    filename: str | None = Field(default=None, max_length=200)
    corrections: dict[str, Any] | None = None


class RuleBody(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    priority: int = 100
    enabled: bool = True
    conditions: dict
    actions: dict
    stop_processing: bool = True


class RuleTestBody(BaseModel):
    conditions: dict
    actions: dict = Field(default_factory=lambda: {"review": True})
    document_id: int | None = None
    sample: dict | None = None


class FolderBody(BaseModel):
    account_id: int
    drive_id: str = Field(min_length=1, max_length=200)
    role: str = Field(pattern="^(archive_root|archive|inbox|review)$")
    description: str | None = Field(default=None, max_length=300)
    import_subfolders: bool = False


class SourceBody(BaseModel):
    kind: str = Field(pattern="^(gmail|drive)$")
    name: str = Field(min_length=1, max_length=120)
    account_id: int
    config: dict = Field(default_factory=dict)
    poll_interval_seconds: int = Field(default=300, ge=60, le=86400)
    enabled: bool = True


class AiProviderBody(BaseModel):
    kind: str = Field(pattern="^(none|ollama|openai_compatible|anthropic|openrouter_decider)$")
    base_url: str = ""
    model: str = ""
    api_key: str | None = None


class OcrProviderBody(BaseModel):
    kind: str = Field(pattern="^(local|nvidia_nemotron_ocr_v2)$")
    api_key: str | None = None
    allow_external_ocr: bool = False


# Hilfen -----------------------------------------------------------------------

DOC_JSON = ("tags", "metadata", "email_meta", "decision")


def doc_out(row: Any, full: bool = False) -> dict:
    d = db.row_to_dict(row, DOC_JSON)
    if not full:
        d.pop("email_meta", None)
        if isinstance(d.get("decision"), dict):
            d["decision"] = {k: d["decision"].get(k) for k in ("folder_drive_id", "confidence", "review_reasons", "rules")}
    folder = db.one("SELECT path FROM drive_folders WHERE drive_id=?", (d.get("target_folder_drive_id"),)) if d.get("target_folder_drive_id") else None
    d["target_folder_path"] = folder["path"] if folder else None
    return d


def get_doc_for(user: User, doc_id: int) -> dict:
    row = db.one(f"SELECT d.* FROM documents d WHERE d.id=? AND {visible_clause(user)}", (doc_id,))
    if row is None:
        raise HTTPException(404, "Dokument nicht gefunden")
    return dict(row)


def fts_query(q: str) -> str:
    tokens = re.findall(r"[\w\-./]+", q, re.UNICODE)[:12]
    return " ".join('"' + t.replace('"', "") + '"*' for t in tokens)


def _drive_folder_path(account_id: int, drive_id: str) -> tuple[str, str, str | None]:
    client = services.drive(account_id)
    meta = client.get(drive_id, "id,name,mimeType,parents")
    if meta.get("mimeType") != FOLDER_MIME:
        raise HTTPException(400, "Die ID gehört zu keinem Ordner")
    names, current = [meta["name"]], meta
    for _ in range(15):
        parents = current.get("parents") or []
        if not parents:
            break
        try:
            current = client.get(parents[0], "id,name,parents")
        except ghttp.GoogleApiError:
            break
        if not current.get("parents"):
            break  # „Meine Ablage“ nicht mit aufnehmen
        names.append(current["name"])
    return meta["name"], "/".join(reversed(names)), (meta.get("parents") or [None])[0]


# Routen -----------------------------------------------------------------------

def register_routes(app: FastAPI) -> None:
    viewer, editor, admin = require("viewer"), require("editor"), require("admin")

    @app.get("/api/health")
    def health():
        s = get_settings()
        hb = db.get_setting("worker_heartbeat")
        return {"status": "ok", "version": __version__, "ocr": ocr_available(), "worker_heartbeat": hb,
                "db": s.db_path.exists()}

    @app.get("/api/me")
    def me(user: User = Depends(current_user)):
        return {"id": user.id, "name": user.display_name or user.name, "role": user.role}

    # Dashboard -----------------------------------------------------------------
    @app.get("/api/dashboard")
    def dashboard(user: User = Depends(viewer)):
        vis = visible_clause(user)
        counts = {r["state"]: r["n"] for r in db.query(f"SELECT state, COUNT(*) n FROM documents d WHERE {vis} GROUP BY state")}
        recent = [doc_out(r) for r in db.query(f"SELECT * FROM documents d WHERE {vis} ORDER BY id DESC LIMIT 15")]
        sources = [dict(r) for r in db.query(
            "SELECT s.id, s.kind, s.name, s.enabled, s.last_sync_at, s.last_status, s.last_error, g.email, g.status AS account_status "
            "FROM sources s LEFT JOIN google_accounts g ON g.id=s.account_id ORDER BY s.id")]
        monthly = [dict(r) for r in db.query(
            f"SELECT substr(created_at,1,7) month, COUNT(*) n FROM documents d WHERE {vis} GROUP BY month ORDER BY month DESC LIMIT 12")]
        ocr_avg = db.one("SELECT AVG(ocr_seconds) a FROM documents WHERE ocr_seconds IS NOT NULL")["a"]
        return {
            "counts": counts,
            "recent": recent,
            "sources": sources,
            "jobs": jobqueue.stats(),
            "monthly": monthly,
            "ocr_avg_seconds": round(ocr_avg, 1) if ocr_avg else None,
            "worker_heartbeat": db.get_setting("worker_heartbeat"),
            "processing_paused": db.get_setting("processing_paused", False),
            "mode": appsettings.get("processing_mode"),
            "ocr_available": ocr_available(),
            "ai_configured": bool((appsettings.get("ai_provider") or {}).get("kind") not in (None, "none")),
        }

    # Dokumente -----------------------------------------------------------------
    @app.get("/api/documents")
    def list_documents(
        user: User = Depends(viewer),
        state: str | None = None,
        q: str | None = Query(default=None, max_length=200),
        document_type: str | None = None,
        sender: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = Query(default=50, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
    ):
        where, params = [visible_clause(user)], []
        if state:
            st = state.split(",")
            where.append(f"d.state IN ({','.join('?' * len(st))})")
            params += st
        if document_type:
            where.append("d.document_type = ?")
            params.append(document_type)
        if sender:
            where.append("d.sender LIKE ?")
            params.append(f"%{sender}%")
        if date_from:
            where.append("d.document_date >= ?")
            params.append(date_from)
        if date_to:
            where.append("d.document_date <= ?")
            params.append(date_to)
        join = ""
        order = "d.id DESC"
        if q and fts_query(q):
            join = "JOIN documents_fts f ON f.rowid=d.id"
            where.append("documents_fts MATCH ?")
            params.append(fts_query(q))
            order = "bm25(documents_fts)"
        sql_where = " AND ".join(where)
        total = db.one(f"SELECT COUNT(*) n FROM documents d {join} WHERE {sql_where}", params)["n"]
        rows = db.query(f"SELECT d.* FROM documents d {join} WHERE {sql_where} ORDER BY {order} LIMIT ? OFFSET ?",
                        (*params, limit, offset))
        return {"total": total, "items": [doc_out(r) for r in rows]}

    @app.get("/api/documents/{doc_id}")
    def get_document(doc_id: int, user: User = Depends(viewer)):
        get_doc_for(user, doc_id)
        row = db.one("SELECT * FROM documents WHERE id=?", (doc_id,))
        d = doc_out(row, full=True)
        d["operations"] = [dict(r) for r in db.query("SELECT * FROM drive_operations WHERE document_id=? ORDER BY id", (doc_id,))]
        d["has_local_file"] = (get_settings().temp_dir / f"doc-{doc_id}" / "original").exists()
        if d.get("duplicate_of"):
            d["duplicate"] = doc_out(db.one("SELECT * FROM documents WHERE id=?", (d["duplicate_of"],)))
        return d

    @app.get("/api/documents/{doc_id}/text")
    def get_text(doc_id: int, user: User = Depends(viewer)):
        get_doc_for(user, doc_id)
        row = db.one("SELECT text, pages, method FROM document_text WHERE document_id=?", (doc_id,))
        if row is None:
            return {"text": "", "pages": [], "method": None}
        return {"text": row["text"], "pages": json.loads(row["pages"]), "method": row["method"]}

    @app.get("/api/documents/{doc_id}/journal")
    def get_journal(doc_id: int, user: User = Depends(viewer)):
        get_doc_for(user, doc_id)
        return [db.row_to_dict(r, ("data",)) for r in db.query("SELECT * FROM journal WHERE document_id=? ORDER BY id", (doc_id,))]

    def _local_copy(d: dict) -> Path:
        s = get_settings()
        local = s.temp_dir / f"doc-{d['id']}" / "original"
        if local.exists():
            return local
        if not d["drive_file_id"] and d["source_kind"] != "drive":
            raise HTTPException(404, "Datei ist lokal nicht mehr vorhanden")
        file_id = d["drive_file_id"] or d["source_ref"]
        account = services.folder_account(d["target_folder_drive_id"]) if d["drive_file_id"] else None
        if account is None:
            src = db.one("SELECT account_id FROM sources WHERE id=?", (d["source_id"],))
            account = src["account_id"] if src else None
        if account is None:
            raise HTTPException(404, "Kein Google-Konto für die Vorschau")
        cache = s.cache_dir / "preview"
        cache.mkdir(parents=True, exist_ok=True)
        local = cache / f"doc-{d['id']}"
        if not local.exists():
            services.drive(account).download(file_id, local, s.max_file_size_mb * 1024 * 1024)
        return local

    @app.get("/api/documents/{doc_id}/file")
    def get_file(doc_id: int, user: User = Depends(viewer), download: bool = False):
        d = get_doc_for(user, doc_id)
        local = _local_copy(d)
        name = d["target_name"] or d["original_filename"]
        resp = FileResponse(local, media_type=d["mime_type"] or "application/octet-stream")
        disp = "attachment" if download else "inline"
        resp.headers["Content-Disposition"] = f"{disp}; filename*=UTF-8''{_quote(name)}"
        # Kein Skript, keine Fremdressourcen; "sandbox" nur für Nicht-PDFs (sonst blockiert
        # der Browser seinen eingebauten PDF-Betrachter).
        csp = "default-src 'none'; img-src 'self'; style-src 'unsafe-inline'; frame-ancestors 'self'"
        if d["mime_type"] != "application/pdf":
            csp = "sandbox; " + csp
        resp.headers["Content-Security-Policy"] = csp
        return resp

    @app.get("/api/documents/{doc_id}/pages/{page}.png")
    def get_page(doc_id: int, page: int, user: User = Depends(viewer), width: int = Query(default=1200, ge=200, le=2400)):
        """Seitenvorschau als PNG (funktioniert auch in der Companion App ohne PDF-Betrachter)."""
        d = get_doc_for(user, doc_id)
        s = get_settings()
        out = s.cache_dir / "pages" / f"doc-{doc_id}-p{page}-w{width}.png"
        if not out.exists():
            local = _local_copy(d)
            out.parent.mkdir(parents=True, exist_ok=True)
            if d["mime_type"] == "application/pdf":
                import pypdfium2 as pdfium

                pdf = pdfium.PdfDocument(str(local))
                try:
                    if not 1 <= page <= len(pdf):
                        raise HTTPException(404, "Seite existiert nicht")
                    pg = pdf[page - 1]
                    scale = width / pg.get_width()
                    pg.render(scale=min(scale, 4.0)).to_pil().save(out, "PNG", optimize=True)
                    pg.close()
                finally:
                    pdf.close()
            elif (d["mime_type"] or "").startswith("image/"):
                if page != 1:
                    raise HTTPException(404, "Seite existiert nicht")
                from PIL import Image

                Image.MAX_IMAGE_PIXELS = s.max_image_pixels
                with Image.open(local) as im:
                    im.thumbnail((width, width * 2))
                    im.convert("RGB").save(out, "PNG", optimize=True)
            else:
                raise HTTPException(415, "Keine Vorschau für diesen Dateityp")
        resp = FileResponse(out, media_type="image/png")
        resp.headers["Cache-Control"] = "private, max-age=3600"
        return resp

    @app.post("/api/documents/upload")
    async def upload(user: User = Depends(editor), files: list[UploadFile] = File(...)):
        s = get_settings()
        limit = s.max_file_size_mb * 1024 * 1024
        results = []
        for f in files[:50]:
            data = await f.read(limit + 1)
            if len(data) > limit:
                results.append({"filename": f.filename, "status": "too_large"})
                continue
            doc_id, status = intake.register_upload(data, Path(f.filename or "upload").name, user.id)
            results.append({"filename": f.filename, "document_id": doc_id, "status": status})
        db.audit("document.upload", user.id, None, count=len(results))
        return {"results": results}

    @app.post("/api/documents/{doc_id}/approve")
    def approve(doc_id: int, body: ApproveBody, user: User = Depends(editor)):
        get_doc_for(user, doc_id)
        return doc_out(db.one("SELECT * FROM documents WHERE id=?", (actions.approve(
            doc_id, user.id, folder_drive_id=body.folder_drive_id, filename=body.filename, corrections=body.corrections)["id"],)))

    @app.post("/api/documents/approve-batch")
    def approve_batch(ids: list[int] = Body(..., embed=True), user: User = Depends(editor)):
        out = []
        for i in ids[:100]:
            try:
                get_doc_for(user, i)
                actions.approve(i, user.id)
                out.append({"id": i, "ok": True})
            except (actions.ActionError, HTTPException) as exc:
                out.append({"id": i, "ok": False, "error": getattr(exc, "detail", str(exc))})
        return {"results": out}

    @app.post("/api/documents/{doc_id}/skip")
    def skip(doc_id: int, user: User = Depends(editor)):
        get_doc_for(user, doc_id)
        actions.skip(doc_id, user.id)
        return {"ok": True}

    @app.post("/api/documents/{doc_id}/reprocess")
    def reprocess(doc_id: int, force_ocr: bool = False, user: User = Depends(editor)):
        get_doc_for(user, doc_id)
        actions.reanalyze(doc_id, user.id, force_ocr=force_ocr)
        return {"ok": True}

    @app.post("/api/documents/{doc_id}/undo")
    def undo(doc_id: int, user: User = Depends(editor)):
        get_doc_for(user, doc_id)
        return doc_out(db.one("SELECT * FROM documents WHERE id=?", (actions.undo(doc_id, user.id)["id"],)))

    @app.get("/api/meta/filters")
    def filters(user: User = Depends(viewer)):
        vis = visible_clause(user)
        return {
            "document_types": [r[0] for r in db.query(f"SELECT DISTINCT document_type FROM documents d WHERE {vis} AND document_type IS NOT NULL ORDER BY 1")],
            "senders": [r[0] for r in db.query(f"SELECT DISTINCT sender FROM documents d WHERE {vis} AND sender IS NOT NULL ORDER BY 1 LIMIT 500")],
            "states": sorted(states.TRANSITIONS),
        }

    # Google --------------------------------------------------------------------
    @app.get("/api/google/status")
    def google_status(user: User = Depends(admin)):
        s = get_settings()
        cfg = oauth.load_client()
        accounts = [dict(r) for r in db.query("SELECT id, email, scopes, status, last_error, updated_at FROM google_accounts ORDER BY id")]
        return {
            "client": None if not cfg else {
                "client_type": cfg["client_type"], "client_id": cfg["client_id"], "project_id": cfg.get("project_id"),
                "redirect_uris": cfg.get("redirect_uris", []),
            },
            "redirect_uri": s.oauth_redirect_uri,
            "redirect_problems": oauth.redirect_uri_problems(cfg, s.oauth_redirect_uri) if cfg else [],
            "required_apis": ["Google Drive API", "Gmail API"],
            "accounts": accounts,
        }

    @app.post("/api/google/client")
    async def google_client(
        user: User = Depends(admin),
        file: UploadFile | None = File(default=None),
        client_id: str | None = Form(default=None),
        client_secret: str | None = Form(default=None),
        client_type: str = Form(default="installed"),
    ):
        try:
            if file is not None:
                raw = await file.read(64 * 1024)
                cfg = oauth.parse_client_json(raw)
            elif client_id and client_secret:
                cfg = oauth.manual_client(client_id, client_secret, "web" if client_type == "web" else "installed")
            else:
                raise oauth.OAuthConfigError("Bitte JSON-Datei hochladen oder Client-ID und -Secret angeben.")
        except oauth.OAuthConfigError as exc:
            raise HTTPException(400, str(exc)) from exc
        oauth.save_client(cfg)
        db.audit("google.client_saved", user.id, None, client_type=cfg["client_type"])
        return {"client_type": cfg["client_type"], "client_id": cfg["client_id"],
                "redirect_problems": oauth.redirect_uri_problems(cfg, get_settings().oauth_redirect_uri)}

    @app.post("/api/google/authorize")
    def google_authorize(
        user: User = Depends(admin),
        drive_mode: str = Body("full", embed=True, pattern="^(full|file)$"),
        gmail: bool = Body(True, embed=True),
    ):
        try:
            url = oauth.start_authorization(get_settings().oauth_redirect_uri, oauth.scopes_for(drive_mode, gmail), user.id)
        except oauth.OAuthConfigError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"auth_url": url, "redirect_uri": get_settings().oauth_redirect_uri}

    @app.post("/api/google/complete")
    def google_complete(redirect_url: str = Body(..., embed=True, max_length=4000), user: User = Depends(admin)):
        try:
            code, state = oauth.parse_redirect(redirect_url)
            return oauth.complete_authorization(code, state)
        except oauth.OAuthConfigError as exc:
            raise HTTPException(400, str(exc)) from exc
        except ghttp.GoogleApiError as exc:
            raise HTTPException(400, f"Google hat den Code abgelehnt: {exc}") from exc

    @app.get("/oauth/callback")
    def google_callback(code: str = "", state: str = "", error: str = ""):
        """Optionaler HTTPS-Callback (nur nötig, wenn eine öffentliche Callback-URL genutzt wird).
        Authentifiziert ausschließlich über den einmaligen ``state``."""
        if error:
            return HTMLResponse(f"<p>Google meldet: {html.escape(error)}</p>", status_code=400)
        try:
            res = oauth.complete_authorization(code, state)
        except (oauth.OAuthConfigError, ghttp.GoogleApiError) as exc:
            return HTMLResponse(f"<p>Verbindung fehlgeschlagen: {html.escape(str(exc))}</p>", status_code=400)
        return HTMLResponse(f"<p>Google-Konto {html.escape(res['email'])} verbunden. Dieses Fenster kann geschlossen werden.</p>")

    @app.post("/api/google/accounts/{account_id}/test")
    def google_test(account_id: int, user: User = Depends(admin)):
        result: dict[str, Any] = {}
        acc = db.one("SELECT * FROM google_accounts WHERE id=?", (account_id,))
        if acc is None:
            raise HTTPException(404, "Konto unbekannt")
        try:
            about = ghttp.request("GET", "https://www.googleapis.com/drive/v3/about",
                                  headers={"Authorization": f"Bearer {oauth.access_token(account_id)}"},
                                  params={"fields": "user(emailAddress),storageQuota"}).json()
            result["drive"] = {"ok": True, "email": about.get("user", {}).get("emailAddress")}
        except ghttp.GoogleApiError as exc:
            result["drive"] = {"ok": False, "error": str(exc)}
        if oauth.has_scope(account_id, oauth.SCOPE_GMAIL_READONLY):
            try:
                result["gmail"] = {"ok": True, "history_id": services.gmail(account_id).profile().get("historyId")}
            except ghttp.GoogleApiError as exc:
                result["gmail"] = {"ok": False, "error": str(exc)}
        else:
            result["gmail"] = {"ok": False, "error": "Gmail-Berechtigung nicht erteilt"}
        return result

    @app.get("/api/google/accounts/{account_id}/folders")
    def google_folders(account_id: int, parent: str = "root", user: User = Depends(admin)):
        items = services.drive(account_id).children(parent, folders_only=True)
        return [{"id": f["id"], "name": f["name"]} for f in sorted(items, key=lambda x: x["name"].lower())]

    # Ordnerfreigaben -----------------------------------------------------------
    @app.get("/api/folders")
    def folders(user: User = Depends(viewer)):
        return [dict(r) for r in db.query("SELECT * FROM drive_folders ORDER BY role, path")]

    @app.post("/api/folders")
    def add_folder(body: FolderBody, user: User = Depends(admin)):
        name, path, parent = _drive_folder_path(body.account_id, body.drive_id)
        _insert_folder(body.account_id, body.drive_id, name, path, parent, body.role, body.description)
        imported = 0
        if body.import_subfolders and body.role in ("archive_root", "archive"):
            imported = _import_tree(body.account_id, body.drive_id, path)
        db.audit("folder.add", user.id, f"drive:{body.drive_id}", role=body.role, imported=imported)
        return {"ok": True, "path": path, "imported": imported}

    @app.patch("/api/folders/{folder_id}")
    def edit_folder(folder_id: int, description: str | None = Body(None, embed=True, max_length=300), user: User = Depends(admin)):
        db.execute("UPDATE drive_folders SET description=? WHERE id=?", (description, folder_id))
        return {"ok": True}

    @app.delete("/api/folders/{folder_id}")
    def remove_folder(folder_id: int, user: User = Depends(admin)):
        db.execute("DELETE FROM drive_folders WHERE id=?", (folder_id,))
        db.audit("folder.remove", user.id, f"folder:{folder_id}")
        return {"ok": True}

    # Quellen -------------------------------------------------------------------
    @app.get("/api/sources")
    def sources(user: User = Depends(viewer)):
        return [db.row_to_dict(r, ("config",)) for r in db.query("SELECT * FROM sources ORDER BY id")]

    @app.post("/api/sources")
    def add_source(body: SourceBody, user: User = Depends(admin)):
        if not db.one("SELECT id FROM google_accounts WHERE id=?", (body.account_id,)):
            raise HTTPException(400, "Google-Konto unbekannt")
        if body.kind == "gmail" and not oauth.has_scope(body.account_id, oauth.SCOPE_GMAIL_READONLY):
            raise HTTPException(400, "Für dieses Konto wurde keine Gmail-Leseberechtigung erteilt")
        if body.kind == "drive":
            ids = body.config.get("folder_ids") or []
            if not ids:
                raise HTTPException(400, "Mindestens einen Eingangsordner angeben")
            for fid in ids:
                if not db.one("SELECT id FROM drive_folders WHERE drive_id=? AND role='inbox'", (fid,)):
                    name, path, parent = _drive_folder_path(body.account_id, fid)
                    _insert_folder(body.account_id, fid, name, path, parent, "inbox", None)
        cur = db.execute(
            "INSERT INTO sources(kind, name, account_id, config, enabled, poll_interval_seconds, created_at) VALUES (?,?,?,?,?,?,?)",
            (body.kind, body.name, body.account_id, json.dumps(body.config), int(body.enabled), body.poll_interval_seconds, db.utcnow()),
        )
        db.audit("source.add", user.id, f"source:{cur.lastrowid}", kind=body.kind)
        return {"id": cur.lastrowid}

    @app.patch("/api/sources/{source_id}")
    def edit_source(source_id: int, enabled: bool | None = Body(None, embed=True), config: dict | None = Body(None, embed=True),
                    user: User = Depends(admin)):
        if enabled is not None:
            db.execute("UPDATE sources SET enabled=? WHERE id=?", (int(enabled), source_id))
        if config is not None:
            db.execute("UPDATE sources SET config=? WHERE id=? AND kind IN ('gmail','drive')", (json.dumps(config), source_id))
        return {"ok": True}

    @app.post("/api/sources/{source_id}/sync")
    def sync_now(source_id: int, user: User = Depends(editor)):
        row = db.one("SELECT kind FROM sources WHERE id=?", (source_id,))
        if row is None:
            raise HTTPException(404, "Quelle unbekannt")
        kind = "scan_local_inbox" if row["kind"] == "local" else "sync_source"
        jid = jobqueue.enqueue(kind, {"source_id": source_id}, priority=60, dedupe_key=f"sync:{source_id}" if kind == "sync_source" else "scan_local")
        return {"queued": jid is not None}

    # Regeln --------------------------------------------------------------------
    @app.get("/api/rules")
    def list_rules(user: User = Depends(viewer)):
        return rules.load_rules()

    def _validate_rule(body: RuleBody | RuleTestBody) -> None:
        try:
            rules.validate_conditions(body.conditions)
            rules.validate_actions(body.actions)
        except rules.RuleError as exc:
            raise HTTPException(400, str(exc)) from exc
        tpl = body.actions.get("filename_template")
        if tpl and naming.validate_template(tpl):
            raise HTTPException(400, "; ".join(naming.validate_template(tpl)))

    @app.post("/api/rules")
    def create_rule(body: RuleBody, user: User = Depends(admin)):
        _validate_rule(body)
        now = db.utcnow()
        cur = db.execute(
            "INSERT INTO rules(name, priority, enabled, conditions, actions, stop_processing, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
            (body.name, body.priority, int(body.enabled), json.dumps(body.conditions), json.dumps(body.actions), int(body.stop_processing), now, now),
        )
        db.audit("rule.create", user.id, f"rule:{cur.lastrowid}")
        return {"id": cur.lastrowid}

    @app.put("/api/rules/{rule_id}")
    def update_rule(rule_id: int, body: RuleBody, user: User = Depends(admin)):
        _validate_rule(body)
        db.execute(
            "UPDATE rules SET name=?, priority=?, enabled=?, conditions=?, actions=?, stop_processing=?, updated_at=? WHERE id=?",
            (body.name, body.priority, int(body.enabled), json.dumps(body.conditions), json.dumps(body.actions), int(body.stop_processing), db.utcnow(), rule_id),
        )
        db.audit("rule.update", user.id, f"rule:{rule_id}")
        return {"ok": True}

    @app.delete("/api/rules/{rule_id}")
    def delete_rule(rule_id: int, user: User = Depends(admin)):
        db.execute("DELETE FROM rules WHERE id=?", (rule_id,))
        db.audit("rule.delete", user.id, f"rule:{rule_id}")
        return {"ok": True}

    @app.post("/api/rules/test")
    def test_rule(body: RuleTestBody, user: User = Depends(editor)):
        """Testlauf: wertet eine (ungespeicherte) Regel gegen ein Dokument oder die letzten 200 aus."""
        _validate_rule(body)
        candidate = [{"id": 0, "name": "Test", "priority": 0, "enabled": True, "conditions": body.conditions,
                      "actions": body.actions, "stop_processing": True}]
        if body.sample is not None:
            return {"matches": [{"sample": True, "matched": bool(rules.apply_rules(candidate, body.sample).matched)}]}
        ids = [body.document_id] if body.document_id else [r["id"] for r in db.query(
            f"SELECT id FROM documents d WHERE {visible_clause(user)} ORDER BY id DESC LIMIT 200")]
        out = []
        for i in ids:
            doc = load(i)
            text = db.one("SELECT text FROM document_text WHERE document_id=?", (i,))
            ctx = rules.build_context(doc, text["text"] if text else "")
            if rules.apply_rules(candidate, ctx).matched:
                out.append({"id": i, "filename": doc["original_filename"], "state": doc["state"]})
        return {"tested": len(ids), "matches": out}

    # Einstellungen / System ------------------------------------------------------
    @app.get("/api/settings")
    def get_settings_route(user: User = Depends(admin)):
        data = appsettings.all_settings()
        s = get_settings()
        data["runtime"] = {
            "ocr_languages": s.ocr_languages, "ocr_max_parallel": s.ocr_max_parallel, "max_file_size_mb": s.max_file_size_mb,
            "processing_window": s.processing_window, "inbox_dir": str(s.inbox_dir), "oauth_redirect_uri": s.oauth_redirect_uri,
        }
        return data

    @app.patch("/api/settings")
    def patch_settings(values: dict = Body(...), user: User = Depends(admin)):
        allowed = {"processing_mode", "auto_threshold", "suggest_threshold", "ai_confidence_cap", "allow_external_ai",
                   "filename_template", "original_strategy", "review_sensitive"}
        for k, v in values.items():
            if k not in allowed:
                raise HTTPException(400, f"Einstellung '{k}' ist nicht änderbar")
            if k == "processing_mode":
                if v not in ("observe", "review", "auto"):
                    raise HTTPException(400, "Ungültiger Modus")
                if v == "auto" and not appsettings.get("test_run_ok"):
                    raise HTTPException(409, "Automatische Ablage erst nach erfolgreichem Testlauf möglich")
            if k == "filename_template" and naming.validate_template(v):
                raise HTTPException(400, "; ".join(naming.validate_template(v)))
            if k in ("auto_threshold", "suggest_threshold", "ai_confidence_cap") and not (0 <= float(v) <= 1):
                raise HTTPException(400, f"{k} muss zwischen 0 und 1 liegen")
            if k == "original_strategy" and v not in ("original_only", "original_plus_derivative", "derivative_only"):
                raise HTTPException(400, "Ungültige Strategie")
            appsettings.set(k, v)
            db.audit("settings.change", user.id, k, value=v if k != "allow_external_ai" else bool(v))
        return appsettings.all_settings()

    @app.put("/api/settings/ocr-provider")
    def set_ocr(body: OcrProviderBody, user: User = Depends(admin)):
        if body.kind == "local":
            appsettings.set("allow_external_ocr", False)
            appsettings.set("ocr_provider", {"kind": "local"})
            crypto.delete_secret("ocr_api_key")
        else:
            if body.api_key and body.api_key.strip():
                crypto.put_secret("ocr_api_key", body.api_key.strip())
            has_key = bool(crypto.get_secret("ocr_api_key"))
            if not has_key:
                raise HTTPException(400, "NVIDIA OCR: API-Key fehlt")
            appsettings.set("ocr_provider", {
                "kind": body.kind, "endpoint": nvidia_ocr.ENDPOINT,
                "model": nvidia_ocr.MODEL, "variant": nvidia_ocr.VARIANT, "has_key": has_key,
            })
            appsettings.set("allow_external_ocr", body.allow_external_ocr)
        db.audit("ocr.provider_set", user.id, body.kind, external_allowed=body.kind != "local" and body.allow_external_ocr)
        return {"ok": True}


    @app.put("/api/settings/ai-provider")
    def set_ai(body: AiProviderBody, user: User = Depends(admin)):
        if body.kind == "none":
            appsettings.set("ai_provider", {"kind": "none"})
            crypto.delete_secret("ai_api_key")
            return {"ok": True}
        if body.kind == decider.KIND:
            # Pin the official API endpoint and exact supported model.
            if body.model and body.model != decider.MODEL:
                raise HTTPException(400, "Decider: Modell nicht unterstützt")
            if body.base_url and body.base_url.rstrip("/") not in (decider.BASE_URL, decider.BASE_URL + "/decisions"):
                raise HTTPException(400, "Decider: ungültiger Endpunkt")
            body.base_url, body.model = decider.BASE_URL, decider.MODEL
            previous = appsettings.get("ai_provider") or {}
            previous_base = (previous.get("base_url") or "").rstrip("/")
            can_reuse = previous_base in ("https://openrouter.ai/api/v1", decider.BASE_URL, decider.BASE_URL + "/decisions")
            if not (body.api_key and body.api_key.strip()):
                body.api_key = None
                if not can_reuse or not crypto.get_secret("ai_api_key"):
                    raise HTTPException(400, "Decider: OpenRouter API-Key fehlt")
        try:
            external = ai_providers.is_external(ai_providers.ProviderConfig(body.kind, body.base_url, body.model))
        except ai_providers.ProviderError as exc:
            raise HTTPException(400, str(exc)) from exc
        if body.api_key:
            crypto.put_secret("ai_api_key", body.api_key)
        has_key = bool(body.api_key) or bool(crypto.get_secret("ai_api_key"))
        appsettings.set("ai_provider", {"kind": body.kind, "base_url": body.base_url, "model": body.model, "has_key": has_key, "external": external})
        db.audit("ai.provider_set", user.id, body.kind, external=external)
        return {"ok": True, "external": external, "allowed": (not external) or bool(appsettings.get("allow_external_ai"))}

    @app.post("/api/processing/{action}")
    def processing(action: str, user: User = Depends(admin)):
        if action not in ("pause", "resume"):
            raise HTTPException(404, "Unbekannte Aktion")
        db.set_setting("processing_paused", action == "pause")
        db.audit(f"processing.{action}", user.id)
        return {"paused": action == "pause"}

    @app.get("/api/jobs")
    def jobs(user: User = Depends(admin), state: str | None = None):
        sql = "SELECT id, kind, payload, priority, state, attempts, max_attempts, run_after, last_error, updated_at FROM jobs"
        rows = db.query(sql + " WHERE state=? ORDER BY id DESC LIMIT 100", (state,)) if state else db.query(sql + " ORDER BY id DESC LIMIT 100")
        return {"stats": jobqueue.stats(), "items": [db.row_to_dict(r, ("payload",)) for r in rows]}

    @app.post("/api/jobs/retry-dead")
    def retry_dead(user: User = Depends(admin)):
        return {"requeued": actions.retry_failed_jobs(user.id)}

    @app.get("/api/users")
    def users(user: User = Depends(admin)):
        return [dict(r) for r in db.query("SELECT id, name, display_name, role, active, created_at, last_seen_at FROM users ORDER BY id")]

    @app.patch("/api/users/{user_id}")
    def edit_user(user_id: int, role: str = Body(..., embed=True, pattern="^(none|viewer|editor|admin)$"), user: User = Depends(admin)):
        if user_id == user.id and role != "admin":
            raise HTTPException(400, "Eigene Administratorrolle kann nicht entzogen werden")
        db.execute("UPDATE users SET role=? WHERE id=?", (role, user_id))
        db.audit("user.role", user.id, f"user:{user_id}", role=role)
        return {"ok": True}

    @app.get("/api/audit")
    def audit_log(user: User = Depends(admin), limit: int = Query(default=100, le=500)):
        return [db.row_to_dict(r, ("details",)) for r in db.query("SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,))]

    # Einrichtung ---------------------------------------------------------------
    @app.get("/api/setup/status")
    def setup_status(user: User = Depends(viewer)):
        s = get_settings()
        free_mb = shutil.disk_usage(s.data_dir).free // (1024 * 1024)
        return {
            "admin_exists": db.one("SELECT COUNT(*) n FROM users WHERE role='admin'")["n"] > 0,
            "you_are_admin": user.is_admin,
            "ocr_available": ocr_available(),
            "free_disk_mb": free_mb,
            "google_client": oauth.load_client() is not None,
            "google_accounts": db.one("SELECT COUNT(*) n FROM google_accounts")["n"],
            "archive_folders": db.one("SELECT COUNT(*) n FROM drive_folders WHERE role IN ('archive','archive_root')")["n"],
            "inbox_sources": db.one("SELECT COUNT(*) n FROM sources WHERE kind IN ('gmail','drive')")["n"],
            "rules": db.one("SELECT COUNT(*) n FROM rules")["n"],
            "ai_provider": appsettings.get("ai_provider"),
            "test_run_ok": appsettings.get("test_run_ok"),
            "setup_completed": appsettings.get("setup_completed"),
            "processing_mode": appsettings.get("processing_mode"),
            "local_inbox": str(s.inbox_dir) if s.local_inbox_enabled else None,
        }

    @app.post("/api/setup/test-run")
    def setup_test_run(user: User = Depends(admin)):
        from ..testrun import run_test

        report = run_test()
        appsettings.set("test_run_ok", report["ok"])
        db.audit("setup.test_run", user.id, None, ok=report["ok"])
        return report

    @app.post("/api/setup/complete")
    def setup_complete(user: User = Depends(admin)):
        appsettings.set("setup_completed", True)
        db.audit("setup.completed", user.id)
        return {"ok": True}

    # Oberfläche ----------------------------------------------------------------
    @app.get("/", include_in_schema=False)
    @app.get("/{path:path}", include_in_schema=False)
    def spa(request: Request, path: str = ""):
        if path.startswith("api/"):
            raise HTTPException(404)
        static = STATIC_DIR
        candidate = (static / path).resolve() if path else None
        if candidate and candidate.is_file() and static.resolve() in candidate.parents:
            resp = FileResponse(candidate)
            if "/assets/" in f"/{path}":
                resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
            return resp
        index = static / "index.html"
        if not index.exists():
            return HTMLResponse("<p>Weboberfläche nicht gebaut. API: <a href='api/docs'>api/docs</a></p>")
        base = request.headers.get("x-ingress-path", "")
        if not re.fullmatch(r"(/[A-Za-z0-9_\-]+)*", base):
            base = ""
        body = index.read_text("utf-8").replace("<head>", f'<head><base href="{html.escape(base)}/">', 1)
        return HTMLResponse(body, headers={"Cache-Control": "no-store"})


def _quote(name: str) -> str:
    from urllib.parse import quote

    return quote(name, safe="")


def _insert_folder(account_id: int, drive_id: str, name: str, path: str, parent: str | None, role: str, description: str | None) -> None:
    db.execute(
        "INSERT INTO drive_folders(account_id, drive_id, name, path, parent_drive_id, role, description, synced_at) VALUES (?,?,?,?,?,?,?,?) "
        "ON CONFLICT(account_id, drive_id) DO UPDATE SET name=excluded.name, path=excluded.path, role=excluded.role, "
        "description=COALESCE(excluded.description, drive_folders.description), synced_at=excluded.synced_at",
        (account_id, drive_id, name, path, parent, role, description, db.utcnow()),
    )


def _import_tree(account_id: int, root_id: str, root_path: str, max_folders: int = 2000) -> int:
    """Liest die bestehende Ordnerstruktur unterhalb eines Archivordners (nur lesend)."""
    client = services.drive(account_id)
    queue, n = [(root_id, root_path)], 0
    while queue and n < max_folders:
        fid, path = queue.pop(0)
        for sub in client.children(fid, folders_only=True):
            sub_path = f"{path}/{sub['name']}"
            existing = db.one("SELECT role FROM drive_folders WHERE account_id=? AND drive_id=?", (account_id, sub["id"]))
            role = existing["role"] if existing and existing["role"] in ("inbox", "review") else "archive"
            _insert_folder(account_id, sub["id"], sub["name"], sub_path, fid, role, None)
            queue.append((sub["id"], sub_path))
            n += 1
    return n


def app_factory() -> FastAPI:
    return create_app()

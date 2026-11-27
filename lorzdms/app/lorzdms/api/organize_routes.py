"""REST-API für Fristen, Vorgänge und Tags."""

from __future__ import annotations

from datetime import date

from fastapi import Body, Depends, FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from .. import appsettings, db, notify, organize
from .deps import User, require, visible_clause


class DeadlineBody(BaseModel):
    title: str = Field(default="", max_length=200)
    due_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    kind: str = "other"
    document_id: int | None = None
    case_id: int | None = None
    remind_days: int | None = Field(default=None, ge=0, le=365)


class CaseBody(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    reference: str | None = Field(default=None, max_length=120)
    document_ids: list[int] = Field(default_factory=list, max_length=200)


class RenameTagBody(BaseModel):
    old: str = Field(min_length=1, max_length=40)
    new: str | None = Field(default=None, max_length=40)


def _deadline_vis(user: User) -> str:
    # Fristen ohne Dokument sind für alle sichtbar, sonst gilt die Sichtbarkeit des Dokuments.
    return "1=1" if user.is_admin else f"(dl.document_id IS NULL OR {visible_clause(user)})"


def _deadline_out(r) -> dict:
    d = dict(r)
    d["days_left"] = (date.fromisoformat(d["due_date"]) - date.today()).days
    d["overdue"] = d["status"] == "open" and d["days_left"] < 0
    return d


DEADLINE_SELECT = (
    "SELECT dl.*, d.title AS document_title, d.original_filename AS document_filename, c.title AS case_title "
    "FROM deadlines dl LEFT JOIN documents d ON d.id=dl.document_id LEFT JOIN cases c ON c.id=dl.case_id"
)


def deadlines_for_document(document_id: int) -> list[dict]:
    return [_deadline_out(r) for r in db.query(f"{DEADLINE_SELECT} WHERE dl.document_id=? ORDER BY dl.due_date", (document_id,))]


def deadline_summary(user: User) -> dict:
    vis = _deadline_vis(user)
    today = date.today().isoformat()
    row = db.one(
        f"SELECT SUM(dl.due_date < ?) overdue, SUM(dl.due_date >= ? AND julianday(dl.due_date) - julianday(?) <= 7) week, COUNT(*) open "
        f"FROM deadlines dl LEFT JOIN documents d ON d.id=dl.document_id WHERE dl.status='open' AND {vis}",
        (today, today, today))
    upcoming = [_deadline_out(r) for r in db.query(
        f"{DEADLINE_SELECT} WHERE dl.status='open' AND {vis} ORDER BY dl.due_date LIMIT 5")]
    return {"overdue": row["overdue"] or 0, "next_7_days": row["week"] or 0, "open": row["open"] or 0, "upcoming": upcoming}


def register(app: FastAPI) -> None:
    viewer, editor, admin = require("viewer"), require("editor"), require("admin")

    def _check_doc(user: User, document_id: int | None) -> None:
        if document_id is None:
            return
        if db.one(f"SELECT 1 FROM documents d WHERE d.id=? AND {visible_clause(user)}", (document_id,)) is None:
            raise HTTPException(404, "Dokument nicht gefunden")

    def _get_deadline(user: User, deadline_id: int):
        row = db.one(f"{DEADLINE_SELECT} WHERE dl.id=? AND {_deadline_vis(user)}", (deadline_id,))
        if row is None:
            raise HTTPException(404, "Frist nicht gefunden")
        return row

    def _guard(fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except organize.OrganizeError as exc:
            raise HTTPException(400, str(exc)) from exc

    # Fristen -------------------------------------------------------------------
    @app.get("/api/deadlines")
    def list_deadlines(
        user: User = Depends(viewer),
        status: str = Query(default="open", pattern="^(open|done|dismissed|all)$"),
        case_id: int | None = None,
        document_id: int | None = None,
        until: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
        limit: int = Query(default=200, ge=1, le=1000),
    ):
        where, params = [_deadline_vis(user)], []
        if status != "all":
            where.append("dl.status=?")
            params.append(status)
        if case_id is not None:
            where.append("dl.case_id=?")
            params.append(case_id)
        if document_id is not None:
            where.append("dl.document_id=?")
            params.append(document_id)
        if until:
            where.append("dl.due_date<=?")
            params.append(until)
        order = "dl.due_date ASC" if status == "open" else "dl.due_date DESC"
        rows = db.query(f"{DEADLINE_SELECT} WHERE {' AND '.join(where)} ORDER BY {order} LIMIT ?", (*params, limit))
        return {"items": [_deadline_out(r) for r in rows], "summary": deadline_summary(user)}

    @app.post("/api/deadlines")
    def add_deadline(body: DeadlineBody, user: User = Depends(editor)):
        _check_doc(user, body.document_id)
        case_id = body.case_id
        if case_id is None and body.document_id is not None:
            linked = [r[0] for r in db.query("SELECT case_id FROM document_cases WHERE document_id=?", (body.document_id,))]
            case_id = linked[0] if len(linked) == 1 else None
        if case_id is not None and db.one("SELECT 1 FROM cases WHERE id=?", (case_id,)) is None:
            raise HTTPException(404, "Vorgang nicht gefunden")
        new_id = _guard(organize.create_deadline, title=body.title, due_date=body.due_date, kind=body.kind,
                        document_id=body.document_id, case_id=case_id, remind_days=body.remind_days, user_id=user.id)
        db.audit("deadline.create", user.id, str(new_id), document_id=body.document_id)
        return _deadline_out(_get_deadline(user, new_id))

    @app.patch("/api/deadlines/{deadline_id}")
    def edit_deadline(deadline_id: int, changes: dict = Body(...), user: User = Depends(editor)):
        _get_deadline(user, deadline_id)
        _guard(organize.update_deadline, deadline_id, changes)
        db.audit("deadline.update", user.id, str(deadline_id), fields=sorted(changes))
        return _deadline_out(_get_deadline(user, deadline_id))

    @app.delete("/api/deadlines/{deadline_id}")
    def delete_deadline(deadline_id: int, user: User = Depends(editor)):
        row = _get_deadline(user, deadline_id)
        if row["source"] == "document":
            # aus dem Dokument erkannte Fristen nur verwerfen, damit sie bei erneuter Analyse nicht wieder auftauchen
            organize.update_deadline(deadline_id, {"status": "dismissed"})
        else:
            db.execute("DELETE FROM deadlines WHERE id=?", (deadline_id,))
        db.audit("deadline.delete", user.id, str(deadline_id))
        return {"ok": True}

    @app.get("/api/deadlines/notify-status")
    def notify_status(user: User = Depends(admin)):
        return {"available": notify.available(), "service": appsettings.get("notify_service"),
                "enabled": appsettings.get("reminders_enabled"), "last_run": db.get_setting("reminders_last_run")}

    @app.post("/api/deadlines/test-notification")
    def test_notification(user: User = Depends(admin)):
        try:
            notify.send("LorzDMS", "Testbenachrichtigung: Fristen-Erinnerungen kommen hier an.", "lorzdms_test")
        except (notify.NotifyError, ValueError) as exc:
            raise HTTPException(409, str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(502, f"Home Assistant nicht erreichbar: {type(exc).__name__}") from exc
        return {"ok": True}

    # Vorgänge ------------------------------------------------------------------
    def _case_out(row, user: User, full: bool = False) -> dict:
        c = dict(row)
        vis = visible_clause(user)
        c["document_count"] = db.one(
            f"SELECT COUNT(*) n FROM document_cases dc JOIN documents d ON d.id=dc.document_id WHERE dc.case_id=? AND {vis}",
            (c["id"],))["n"]
        nxt = db.one(
            f"SELECT MIN(dl.due_date) due, COUNT(*) n FROM deadlines dl LEFT JOIN documents d ON d.id=dl.document_id "
            f"WHERE dl.case_id=? AND dl.status='open' AND {_deadline_vis(user)}", (c["id"],))
        c["open_deadlines"], c["next_due"] = nxt["n"], nxt["due"]
        if full:
            from .app import doc_out

            c["documents"] = [
                {**doc_out(r), "link_source": r["link_source"]}
                for r in db.query(
                    f"SELECT d.*, dc.source AS link_source FROM document_cases dc JOIN documents d ON d.id=dc.document_id "
                    f"WHERE dc.case_id=? AND {vis} ORDER BY COALESCE(d.document_date, d.created_at) DESC", (c["id"],))
            ]
            c["deadlines"] = [_deadline_out(r) for r in db.query(
                f"{DEADLINE_SELECT} WHERE dl.case_id=? AND {_deadline_vis(user)} ORDER BY dl.status='open' DESC, dl.due_date",
                (c["id"],))]
        return c

    def _get_case(case_id: int):
        row = db.one("SELECT * FROM cases WHERE id=?", (case_id,))
        if row is None:
            raise HTTPException(404, "Vorgang nicht gefunden")
        return row

    @app.get("/api/cases")
    def list_cases(user: User = Depends(viewer), status: str = Query(default="open", pattern="^(open|closed|all)$"),
                   q: str | None = Query(default=None, max_length=200)):
        where, params = [], []
        if status != "all":
            where.append("status=?")
            params.append(status)
        if q:
            where.append("(title LIKE ? OR reference LIKE ? COLLATE NOCASE)")
            params += [f"%{q}%", f"%{q}%"]
        sql = "SELECT * FROM cases" + (f" WHERE {' AND '.join(where)}" if where else "") + " ORDER BY updated_at DESC LIMIT 500"
        return {"items": [_case_out(r, user) for r in db.query(sql, params)]}

    @app.post("/api/cases")
    def add_case(body: CaseBody, user: User = Depends(editor)):
        for did in body.document_ids:
            _check_doc(user, did)
        with db.tx():
            case_id = _guard(organize.create_case, body.title, description=body.description, reference=body.reference, user_id=user.id)
            for did in body.document_ids:
                organize.link(case_id, did)
        db.audit("case.create", user.id, str(case_id), documents=len(body.document_ids))
        return _case_out(_get_case(case_id), user, full=True)

    @app.get("/api/cases/{case_id}")
    def get_case(case_id: int, user: User = Depends(viewer)):
        return _case_out(_get_case(case_id), user, full=True)

    @app.patch("/api/cases/{case_id}")
    def edit_case(case_id: int, changes: dict = Body(...), user: User = Depends(editor)):
        _get_case(case_id)
        _guard(organize.update_case, case_id, changes)
        db.audit("case.update", user.id, str(case_id), fields=sorted(changes))
        return _case_out(_get_case(case_id), user, full=True)

    @app.delete("/api/cases/{case_id}")
    def delete_case(case_id: int, user: User = Depends(admin)):
        _get_case(case_id)
        # Dokumente bleiben unverändert; nur die Zuordnung und der Vorgang selbst werden entfernt.
        db.execute("DELETE FROM cases WHERE id=?", (case_id,))
        db.audit("case.delete", user.id, str(case_id))
        return {"ok": True}

    @app.post("/api/cases/{case_id}/documents")
    def link_document(case_id: int, document_id: int = Body(..., embed=True), user: User = Depends(editor)):
        _get_case(case_id)
        _check_doc(user, document_id)
        organize.link(case_id, document_id)
        db.audit("case.link", user.id, str(case_id), document_id=document_id)
        return _case_out(_get_case(case_id), user, full=True)

    @app.delete("/api/cases/{case_id}/documents/{document_id}")
    def unlink_document(case_id: int, document_id: int, user: User = Depends(editor)):
        _get_case(case_id)
        _check_doc(user, document_id)
        organize.unlink(case_id, document_id)
        db.audit("case.unlink", user.id, str(case_id), document_id=document_id)
        return {"ok": True}

    # Tags ----------------------------------------------------------------------
    @app.get("/api/tags")
    def list_tags(user: User = Depends(viewer)):
        return {"items": organize.tag_counts(visible_clause(user))}

    @app.put("/api/documents/{doc_id}/tags")
    def put_tags(doc_id: int, tags: list[str] = Body(..., embed=True, max_length=30), user: User = Depends(editor)):
        _check_doc(user, doc_id)
        clean = _guard(organize.set_tags, doc_id, tags)
        db.audit("document.tags", user.id, str(doc_id), count=len(clean))
        return {"tags": clean}

    @app.post("/api/tags/rename")
    def rename_tag(body: RenameTagBody, user: User = Depends(admin)):
        n = _guard(organize.rename_tag, body.old, body.new or None)
        db.audit("tags.rename" if body.new else "tags.remove", user.id, body.old, new=body.new, documents=n)
        return {"changed": n}

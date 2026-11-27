"""Fristen, Erinnerungen, Vorgänge und Tags.

- Fristen entstehen manuell oder aus der Dokumentanalyse (Fälligkeitsdatum, erkannte Fristen).
  Eine einmal angelegte Frist wird bei erneuter Analyse nicht überschrieben, damit erledigte
  oder verworfene Fristen nicht wieder auftauchen.
- Vorgänge bündeln Dokumente und Fristen. Dokumente werden automatisch einem offenen Vorgang
  zugeordnet, wenn eine erkannte Referenz (Aktenzeichen, Vertrags-, Versicherungs- oder
  Kundennummer) exakt der Referenz des Vorgangs entspricht.
- Tags sind freie Schlagwörter in ``documents.tags`` (JSON-Liste).
"""

from __future__ import annotations

import json
import logging
import re
from datetime import date, timedelta
from typing import Any

from . import appsettings, db

log = logging.getLogger("lorzdms.organize")

KINDS = ("payment", "cancellation", "objection", "response", "appointment", "resubmission", "other")
KIND_LABELS = {
    "payment": "Zahlung", "cancellation": "Kündigung", "objection": "Widerspruch", "response": "Antwort",
    "appointment": "Termin", "resubmission": "Wiedervorlage", "other": "Frist",
}
REFERENCE_KEYS = ("case_number", "contract_number", "insurance_number", "customer_number")
TAG_RE = re.compile(r"^[\w äöüÄÖÜß&+./-]{1,40}$", re.UNICODE)
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class OrganizeError(ValueError):
    pass


# Hilfen -----------------------------------------------------------------------

def parse_date(value: str | None) -> str:
    if not value or not DATE_RE.match(value):
        raise OrganizeError("Datum muss im Format JJJJ-MM-TT angegeben werden")
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise OrganizeError("Ungültiges Datum") from exc
    return value


def normalize_tag(tag: str) -> str:
    t = " ".join(str(tag).split()).strip()
    if not TAG_RE.match(t):
        raise OrganizeError(f"Ungültiger Tag: {tag!r} (1–40 Zeichen, keine Sonderzeichen wie , ; \" < >)")
    return t


def normalize_tags(tags: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for t in tags:
        n = normalize_tag(t)
        if n.lower() not in seen:
            seen.add(n.lower())
            out.append(n)
    if len(out) > 30:
        raise OrganizeError("Höchstens 30 Tags je Dokument")
    return out


def _clean_ref(value: Any) -> str | None:
    """Referenz so speichern, wie sie eingegeben wurde (nur Leerraum bereinigt)."""
    if value is None:
        return None
    s = " ".join(str(value).split())[:120]
    return s or None


def _ref_key(value: Any) -> str | None:
    """Vergleichsschlüssel: nur Buchstaben und Ziffern, Großschreibung (PK 4711/26 == pk-4711-26)."""
    if value is None:
        return None
    s = re.sub(r"[\W_]+", "", str(value), flags=re.UNICODE).upper()
    return s or None


def _today() -> date:
    return date.today()


# Fristen ------------------------------------------------------------------------

def deadline_title(kind: str, doc: dict | None) -> str:
    label = KIND_LABELS.get(kind, "Frist")
    if not doc:
        return label
    who = doc.get("sender") or (doc.get("metadata") or {}).get("sender")
    what = doc.get("document_type") or (doc.get("metadata") or {}).get("document_type")
    parts = [p for p in (who, what) if p]
    return f"{label}: {' – '.join(parts)}"[:200] if parts else label


def sync_from_analysis(doc: dict, meta: dict) -> int:
    """Legt Fristen aus dem Analyseergebnis an (idempotent). Rückgabe: Anzahl neu angelegter."""
    candidates: list[dict] = []
    if meta.get("due_date"):
        candidates.append({"kind": "payment" if (meta.get("amount") is not None or "rechnung" in str(meta.get("document_type") or "").lower()) else "other",
                           "date": meta["due_date"], "explicit": True, "quote": None})
    for dl in meta.get("deadlines") or []:
        if isinstance(dl, dict) and dl.get("date"):
            candidates.append({"kind": dl.get("kind") if dl.get("kind") in KINDS else "other", "date": dl["date"],
                               "explicit": bool(dl.get("explicit")), "quote": dl.get("quote")})
    created = 0
    default_days = int(appsettings.get("reminder_days_default") or 3)
    now = db.utcnow()
    for c in candidates:
        try:
            due = parse_date(c["date"])
        except OrganizeError:
            continue
        cur = db.execute(
            "INSERT OR IGNORE INTO deadlines(document_id, title, kind, due_date, source, explicit, quote, remind_days, created_at, updated_at) "
            "VALUES (?,?,?,?, 'document', ?,?,?,?,?)",
            (doc["id"], deadline_title(c["kind"], doc), c["kind"], due, 1 if c["explicit"] else 0,
             (c.get("quote") or None) and str(c["quote"])[:300], default_days, now, now),
        )
        created += cur.rowcount
    if created:
        case_ids = [r[0] for r in db.query("SELECT case_id FROM document_cases WHERE document_id=?", (doc["id"],))]
        if len(case_ids) == 1:
            db.execute("UPDATE deadlines SET case_id=? WHERE document_id=? AND case_id IS NULL", (case_ids[0], doc["id"]))
    return created


def create_deadline(*, title: str, due_date: str, kind: str = "other", document_id: int | None = None,
                    case_id: int | None = None, remind_days: int | None = None, user_id: int | None = None) -> int:
    if kind not in KINDS:
        raise OrganizeError("Unbekannte Fristart")
    title = (title or "").strip()[:200] or KIND_LABELS[kind]
    days = int(appsettings.get("reminder_days_default") or 3) if remind_days is None else int(remind_days)
    if not 0 <= days <= 365:
        raise OrganizeError("Erinnerung 0–365 Tage vorher")
    now = db.utcnow()
    return db.execute(
        "INSERT INTO deadlines(document_id, case_id, title, kind, due_date, source, remind_days, created_by, created_at, updated_at) "
        "VALUES (?,?,?,?,?, 'manual', ?,?,?,?)",
        (document_id, case_id, title, kind, parse_date(due_date), days, user_id, now, now),
    ).lastrowid


def update_deadline(deadline_id: int, changes: dict) -> None:
    row = db.one("SELECT * FROM deadlines WHERE id=?", (deadline_id,))
    if row is None:
        raise OrganizeError("Frist nicht gefunden")
    sets, params = [], []
    for key, value in changes.items():
        if key == "status":
            if value not in ("open", "done", "dismissed"):
                raise OrganizeError("Ungültiger Status")
            sets += ["status=?", "done_at=?"]
            params += [value, db.utcnow() if value != "open" else None]
        elif key == "due_date":
            sets += ["due_date=?", "notified_stage=0", "notified_at=NULL"]
            params.append(parse_date(value))
        elif key == "title":
            sets.append("title=?")
            params.append((str(value).strip() or row["title"])[:200])
        elif key == "kind":
            if value not in KINDS:
                raise OrganizeError("Unbekannte Fristart")
            sets.append("kind=?")
            params.append(value)
        elif key == "remind_days":
            if not 0 <= int(value) <= 365:
                raise OrganizeError("Erinnerung 0–365 Tage vorher")
            sets += ["remind_days=?", "notified_stage=0", "notified_at=NULL"]
            params.append(int(value))
        elif key == "case_id":
            if value is not None and db.one("SELECT 1 FROM cases WHERE id=?", (value,)) is None:
                raise OrganizeError("Vorgang nicht gefunden")
            sets.append("case_id=?")
            params.append(value)
        else:
            raise OrganizeError(f"Feld '{key}' ist nicht änderbar")
    if sets:
        sets.append("updated_at=?")
        params.append(db.utcnow())
        db.execute(f"UPDATE deadlines SET {', '.join(sets)} WHERE id=?", (*params, deadline_id))


def due_reminders(today: date | None = None) -> list[dict]:
    """Offene Fristen, für die jetzt eine Erinnerung fällig ist (Stufe 1 vorab, Stufe 2 am Fälligkeitstag)."""
    today = today or _today()
    out = []
    for r in db.query("SELECT * FROM deadlines WHERE status='open' AND notified_stage < 2 ORDER BY due_date"):
        due = date.fromisoformat(r["due_date"])
        stage = 2 if today >= due else (1 if today >= due - timedelta(days=r["remind_days"]) else 0)
        if stage > r["notified_stage"]:
            d = dict(r)
            d["stage"] = stage
            d["days_left"] = (due - today).days
            out.append(d)
    return out


def reminder_text(d: dict) -> tuple[str, str]:
    due = date.fromisoformat(d["due_date"]).strftime("%d.%m.%Y")
    if d["days_left"] < 0:
        when = f"seit {-d['days_left']} Tag(en) überfällig ({due})"
    elif d["days_left"] == 0:
        when = f"heute fällig ({due})"
    else:
        when = f"fällig in {d['days_left']} Tag(en) am {due}"
    return "LorzDMS: Frist", f"{d['title']} – {when}"


def run_reminders(notifier, today: date | None = None) -> int:
    """Sendet fällige Erinnerungen über ``notifier(title, message, tag)``. Rückgabe: Anzahl gesendet."""
    sent = 0
    for d in due_reminders(today):
        title, message = reminder_text(d)
        notifier(title, message, f"lorzdms_deadline_{d['id']}")
        db.execute("UPDATE deadlines SET notified_stage=?, notified_at=? WHERE id=?", (d["stage"], db.utcnow(), d["id"]))
        sent += 1
    return sent


# Vorgänge -----------------------------------------------------------------------

def create_case(title: str, *, description: str | None = None, reference: str | None = None, user_id: int | None = None) -> int:
    title = (title or "").strip()
    if not title:
        raise OrganizeError("Titel fehlt")
    now = db.utcnow()
    return db.execute(
        "INSERT INTO cases(title, description, reference, created_by, created_at, updated_at) VALUES (?,?,?,?,?,?)",
        (title[:200], (description or "")[:4000] or None, _clean_ref(reference), user_id, now, now),
    ).lastrowid


def update_case(case_id: int, changes: dict) -> None:
    if db.one("SELECT 1 FROM cases WHERE id=?", (case_id,)) is None:
        raise OrganizeError("Vorgang nicht gefunden")
    sets, params = [], []
    for key, value in changes.items():
        if key == "title":
            if not str(value or "").strip():
                raise OrganizeError("Titel fehlt")
            sets.append("title=?")
            params.append(str(value).strip()[:200])
        elif key == "description":
            sets.append("description=?")
            params.append((value or "")[:4000] or None)
        elif key == "reference":
            sets.append("reference=?")
            params.append(_clean_ref(value))
        elif key == "status":
            if value not in ("open", "closed"):
                raise OrganizeError("Ungültiger Status")
            sets += ["status=?", "closed_at=?"]
            params += [value, db.utcnow() if value == "closed" else None]
        else:
            raise OrganizeError(f"Feld '{key}' ist nicht änderbar")
    if sets:
        sets.append("updated_at=?")
        params.append(db.utcnow())
        db.execute(f"UPDATE cases SET {', '.join(sets)} WHERE id=?", (*params, case_id))


def link(case_id: int, document_id: int, source: str = "manual") -> bool:
    if db.one("SELECT 1 FROM cases WHERE id=?", (case_id,)) is None:
        raise OrganizeError("Vorgang nicht gefunden")
    cur = db.execute("INSERT OR IGNORE INTO document_cases(document_id, case_id, source, created_at) VALUES (?,?,?,?)",
                     (document_id, case_id, source, db.utcnow()))
    db.execute("UPDATE deadlines SET case_id=? WHERE document_id=? AND case_id IS NULL", (case_id, document_id))
    db.execute("UPDATE cases SET updated_at=? WHERE id=?", (db.utcnow(), case_id))
    return cur.rowcount > 0


def unlink(case_id: int, document_id: int) -> None:
    db.execute("DELETE FROM document_cases WHERE case_id=? AND document_id=?", (case_id, document_id))
    db.execute("UPDATE deadlines SET case_id=NULL WHERE document_id=? AND case_id=?", (document_id, case_id))


def auto_link(doc: dict, meta: dict) -> list[int]:
    """Ordnet ein Dokument offenen Vorgängen mit exakt gleicher Referenz zu."""
    refs = {r for r in (_ref_key(meta.get(k)) for k in REFERENCE_KEYS) if r and len(r) >= 4}
    if not refs:
        return []
    linked = []
    for row in db.query("SELECT id, reference FROM cases WHERE status='open' AND reference IS NOT NULL"):
        if _ref_key(row["reference"]) in refs and link(row["id"], doc["id"], source="auto"):
            linked.append(row["id"])
    return linked


def cases_for_document(document_id: int) -> list[dict]:
    return [dict(r) for r in db.query(
        "SELECT c.id, c.title, c.status, c.reference, dc.source FROM document_cases dc JOIN cases c ON c.id=dc.case_id "
        "WHERE dc.document_id=? ORDER BY c.title", (document_id,))]


# Tags ---------------------------------------------------------------------------

def set_tags(document_id: int, tags: list[str]) -> list[str]:
    clean = normalize_tags(tags)
    db.execute("UPDATE documents SET tags=?, updated_at=? WHERE id=?", (json.dumps(clean, ensure_ascii=False), db.utcnow(), document_id))
    return clean


def tag_counts(visibility_sql: str = "1=1") -> list[dict]:
    rows = db.query(
        f"SELECT j.value AS tag, COUNT(*) AS n FROM documents d, json_each(CASE WHEN json_valid(d.tags) THEN d.tags ELSE '[]' END) j "
        f"WHERE {visibility_sql} GROUP BY j.value ORDER BY n DESC, j.value COLLATE NOCASE")
    return [{"tag": r["tag"], "count": r["n"]} for r in rows]


def rename_tag(old: str, new: str | None) -> int:
    """Benennt einen Tag in allen Dokumenten um (Zusammenführung, falls ``new`` schon existiert)
    oder entfernt ihn (``new`` = None). Rückgabe: Anzahl geänderter Dokumente."""
    target = normalize_tag(new) if new else None
    changed = 0
    rows = db.query("SELECT d.id, d.tags FROM documents d, json_each(CASE WHEN json_valid(d.tags) THEN d.tags ELSE '[]' END) j "
                    "WHERE j.value = ?", (old,))
    with db.tx():
        for r in rows:
            tags = [t for t in json.loads(r["tags"]) if t != old]
            if target and target.lower() not in {t.lower() for t in tags}:
                tags.append(target)
            db.execute("UPDATE documents SET tags=?, updated_at=? WHERE id=?", (json.dumps(tags, ensure_ascii=False), db.utcnow(), r["id"]))
            changed += 1
    return changed

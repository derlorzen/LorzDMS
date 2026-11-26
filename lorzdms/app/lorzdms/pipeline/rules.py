"""Deterministische Regel-Engine.

Bedingungen (JSON):
    {"all": [ ... ]} | {"any": [ ... ]} | {"not": {...}}
    {"field": "sender_domain", "op": "equals", "value": "aok.de"}

Operatoren: equals, not_equals, contains, not_contains, starts_with, ends_with,
regex, in, exists, gte, lte.

Aktionen (JSON-Objekt, alle optional):
    folder_drive_id, document_type, sender, tags (Liste), filename_template,
    review (bool), exclude (bool), visibility ('members'|'admins')

Regeln werden nach ``priority`` (aufsteigend) ausgewertet. Deterministische Regeln haben
Vorrang vor KI-Vorschlägen.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from .. import db

MAX_REGEX_LEN = 500
MAX_TEXT_FOR_REGEX = 200_000
FIELDS = {
    "filename", "text", "subject", "sender_email", "sender_domain", "sender_name",
    "source_kind", "source_name", "document_type", "sender", "confidence", "mime_type",
    "source_folder", "tags",
}
OPS = {"equals", "not_equals", "contains", "not_contains", "starts_with", "ends_with", "regex", "in", "exists", "gte", "lte"}
ACTION_KEYS = {"folder_drive_id", "document_type", "sender", "tags", "filename_template", "review", "exclude", "visibility"}


class RuleError(ValueError):
    pass


def validate_conditions(node: Any, depth: int = 0) -> None:
    if depth > 8:
        raise RuleError("Bedingungen zu tief verschachtelt")
    if not isinstance(node, dict):
        raise RuleError("Bedingung muss ein Objekt sein")
    if "all" in node or "any" in node:
        key = "all" if "all" in node else "any"
        items = node[key]
        if not isinstance(items, list) or not items:
            raise RuleError(f"'{key}' braucht eine nicht-leere Liste")
        for it in items:
            validate_conditions(it, depth + 1)
        return
    if "not" in node:
        validate_conditions(node["not"], depth + 1)
        return
    f, op = node.get("field"), node.get("op")
    if f not in FIELDS:
        raise RuleError(f"Unbekanntes Feld: {f}")
    if op not in OPS:
        raise RuleError(f"Unbekannter Operator: {op}")
    if op == "regex":
        pattern = node.get("value")
        if not isinstance(pattern, str) or len(pattern) > MAX_REGEX_LEN:
            raise RuleError("Regex fehlt oder ist zu lang")
        try:
            re.compile(pattern)
        except re.error as exc:
            raise RuleError(f"Ungültiger regulärer Ausdruck: {exc}") from exc


def validate_actions(actions: Any) -> None:
    if not isinstance(actions, dict) or not actions:
        raise RuleError("Aktionen müssen ein nicht-leeres Objekt sein")
    unknown = set(actions) - ACTION_KEYS
    if unknown:
        raise RuleError(f"Unbekannte Aktionen: {', '.join(sorted(unknown))}")
    if "tags" in actions and not (isinstance(actions["tags"], list) and all(isinstance(t, str) for t in actions["tags"])):
        raise RuleError("tags muss eine Liste von Texten sein")
    if "visibility" in actions and actions["visibility"] not in ("members", "admins"):
        raise RuleError("visibility muss 'members' oder 'admins' sein")


def _as_text(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, list):
        return " ".join(map(str, v))
    return str(v)


def evaluate(node: dict, ctx: dict) -> bool:
    if "all" in node:
        return all(evaluate(n, ctx) for n in node["all"])
    if "any" in node:
        return any(evaluate(n, ctx) for n in node["any"])
    if "not" in node:
        return not evaluate(node["not"], ctx)
    f, op, val = node["field"], node["op"], node.get("value")
    actual = ctx.get(f)
    case_sensitive = bool(node.get("case_sensitive", False))
    if op == "exists":
        return actual not in (None, "", [])
    if op in ("gte", "lte"):
        try:
            a, b = float(actual), float(val)
        except (TypeError, ValueError):
            return False
        return a >= b if op == "gte" else a <= b
    a = _as_text(actual)
    if op == "regex":
        flags = 0 if case_sensitive else re.IGNORECASE
        return re.search(val, a[:MAX_TEXT_FOR_REGEX], flags) is not None
    if op == "in":
        options = val if isinstance(val, list) else [val]
        if case_sensitive:
            return a in options
        return a.lower() in {str(o).lower() for o in options}
    b = _as_text(val)
    if not case_sensitive:
        a, b = a.lower(), b.lower()
    return {
        "equals": a == b,
        "not_equals": a != b,
        "contains": b in a,
        "not_contains": b not in a,
        "starts_with": a.startswith(b),
        "ends_with": a.endswith(b),
    }[op]


@dataclass
class RuleOutcome:
    matched: list[dict] = field(default_factory=list)
    actions: dict = field(default_factory=dict)
    conflicts: list[str] = field(default_factory=list)


def apply_rules(rules: list[dict], ctx: dict) -> RuleOutcome:
    out = RuleOutcome()
    for rule in sorted(rules, key=lambda r: (r["priority"], r["id"])):
        if not rule.get("enabled", True):
            continue
        try:
            hit = evaluate(rule["conditions"], ctx)
        except (KeyError, TypeError, re.error):
            continue
        if not hit:
            continue
        out.matched.append({"id": rule["id"], "name": rule["name"]})
        for key, value in rule["actions"].items():
            if key == "tags":
                out.actions.setdefault("tags", [])
                out.actions["tags"] += [t for t in value if t not in out.actions["tags"]]
            elif key in out.actions and out.actions[key] != value:
                out.conflicts.append(f"Regel '{rule['name']}' widerspricht bei '{key}'")
            else:
                out.actions.setdefault(key, value)
        if rule.get("stop_processing", True):
            break
    return out


def load_rules() -> list[dict]:
    rows = db.query("SELECT * FROM rules ORDER BY priority, id")
    out = []
    for r in rows:
        d = dict(r)
        d["conditions"] = json.loads(d["conditions"])
        d["actions"] = json.loads(d["actions"])
        d["enabled"] = bool(d["enabled"])
        d["stop_processing"] = bool(d["stop_processing"])
        out.append(d)
    return out


def build_context(doc: dict, text: str, folder_path: str | None = None) -> dict:
    email = doc.get("email_meta") or {}
    if isinstance(email, str):
        email = json.loads(email or "{}")
    sender_email = (email.get("from_email") or "").lower()
    return {
        "filename": doc.get("original_filename"),
        "text": text,
        "subject": email.get("subject"),
        "sender_email": sender_email,
        "sender_domain": sender_email.rsplit("@", 1)[-1] if "@" in sender_email else "",
        "sender_name": email.get("from_name"),
        "source_kind": doc.get("source_kind"),
        "source_name": doc.get("source_name"),
        "document_type": doc.get("document_type"),
        "sender": doc.get("sender"),
        "confidence": doc.get("confidence"),
        "mime_type": doc.get("mime_type"),
        "source_folder": folder_path,
        "tags": doc.get("tags") if isinstance(doc.get("tags"), list) else json.loads(doc.get("tags") or "[]"),
    }

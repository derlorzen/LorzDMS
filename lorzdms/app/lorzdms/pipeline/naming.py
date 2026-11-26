"""Dateinamensvorlagen.

Beispiel: ``{document_date}_{sender}_{document_type}_{reference}`` →
``2026-11-18_Hostinger_Rechnung_123456.pdf``. Fehlende Felder entfallen samt Trenner.
"""

from __future__ import annotations

import re
import string
import unicodedata
from datetime import date

DEFAULT_TEMPLATE = "{document_date}_{sender}_{document_type}_{reference}"
MAX_STEM = 150
_FORBIDDEN = re.compile(r'[\\/:*?"<>|\x00-\x1f\x7f]')
_WS = re.compile(r"\s+")
_MULTI_SEP = re.compile(r"[_\-\.]{2,}")
FIELDS = {
    "document_date", "sender", "document_type", "reference", "title",
    "original_name", "year", "month", "person", "amount",
}


def clean_part(value: str, *, spaces: str = "_") -> str:
    value = unicodedata.normalize("NFC", str(value))
    value = _FORBIDDEN.sub(" ", value)
    value = _WS.sub(" ", value).strip(" ._-")
    return value.replace(" ", spaces)


def _normalize_date(value: str | None) -> str | None:
    if not value:
        return None
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", value)
    if m:
        try:
            return date(int(m[1]), int(m[2]), int(m[3])).isoformat()
        except ValueError:
            return None
    m = re.match(r"^(\d{1,2})\.(\d{1,2})\.(\d{4})$", value.strip())
    if m:
        try:
            return date(int(m[3]), int(m[2]), int(m[1])).isoformat()
        except ValueError:
            return None
    return None


def validate_template(template: str) -> list[str]:
    errors = []
    try:
        parsed = list(string.Formatter().parse(template))
    except ValueError as exc:
        return [f"Ungültige Vorlage: {exc}"]
    for _, name, spec, conv in parsed:
        if name is None:
            continue
        if name not in FIELDS:
            errors.append(f"Unbekanntes Feld: {name}")
        if spec or conv:
            errors.append(f"Formatangaben sind nicht erlaubt: {name}")
    return errors


def render(template: str, meta: dict, original_name: str, extension: str) -> str:
    if validate_template(template):
        template = DEFAULT_TEMPLATE
    d = _normalize_date(meta.get("document_date"))
    values = {
        "document_date": d,
        "sender": meta.get("sender"),
        "document_type": meta.get("document_type"),
        "reference": meta.get("reference") or meta.get("invoice_number") or meta.get("case_number"),
        "title": meta.get("title"),
        "original_name": original_name.rsplit(".", 1)[0],
        "year": d[:4] if d else None,
        "month": d[5:7] if d else None,
        "person": meta.get("person"),
        "amount": meta.get("amount"),
    }
    out = []
    for literal, name, _, _ in string.Formatter().parse(template):
        out.append(("L", literal))
        if name is not None:
            v = values.get(name)
            out.append(("V", clean_part(v) if v not in (None, "") else ""))
    # Trenner entfernen, die an ein leeres Feld grenzen
    text = ""
    for kind, val in out:
        text += val if kind == "V" else _FORBIDDEN.sub("_", val).replace(" ", "_")
    text = _MULTI_SEP.sub(lambda m: m.group(0)[0], text).strip(" _-.")
    if not text:
        text = clean_part(original_name.rsplit(".", 1)[0]) or "Dokument"
    text = text[:MAX_STEM].rstrip(" _-.")
    ext = extension if extension.startswith(".") else f".{extension}"
    return f"{text}{ext.lower()}"


def resolve_conflict(name: str, existing: set[str]) -> str:
    if name not in existing:
        return name
    stem, dot, ext = name.rpartition(".")
    if not dot:
        stem, ext = name, ""
    i = 2
    while True:
        candidate = f"{stem}_{i}.{ext}" if ext else f"{stem}_{i}"
        if candidate not in existing:
            return candidate
        i += 1

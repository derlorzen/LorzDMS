"""Testlauf im Einrichtungsassistenten.

Prüft lokal und ohne Veränderungen in Google Drive: OCR an einem mitgelieferten
Scan-Beispiel, Regelauswertung, Dateinamensvorlage, Erreichbarkeit der freigegebenen
Archivordner und (falls konfiguriert) den KI-Provider. Ergebnis ist ein Bericht mit
einzelnen Prüfpunkten; nur wenn alle Pflichtpunkte bestehen, gilt der Test als bestanden.
"""

from __future__ import annotations

import shutil
import tempfile
from importlib import resources
from pathlib import Path

from . import appsettings, db, services
from .config import get_settings
from .google import http as ghttp
from .pipeline import naming, rules, text as textmod


def run_test() -> dict:
    s = get_settings()
    checks: list[dict] = []

    def add(name: str, ok: bool, detail: str = "", required: bool = True) -> None:
        checks.append({"name": name, "ok": ok, "detail": detail, "required": required})

    sample = resources.files("lorzdms.samples").joinpath("testbrief-scan.pdf")
    with tempfile.TemporaryDirectory(dir=s.temp_dir) as tmp:
        work = Path(tmp)
        src = work / "sample.pdf"
        with resources.as_file(sample) as p:
            shutil.copy(p, src)
        try:
            res = textmod.extract(src, "application/pdf", work, languages=s.ocr_languages, timeout=min(s.ocr_timeout_seconds, 300))
            found = "TEST-0001" in res.text.replace(" ", "")
            add("OCR (lokal)", res.ocr_used and found, f"{res.method}, {res.ocr_seconds or 0:.1f}s" + ("" if found else ", Testtext nicht erkannt"))
            text = res.text
        except (textmod.OcrFailed, textmod.OcrUnavailable) as exc:
            add("OCR (lokal)", False, str(exc))
            text = ""
    ctx = rules.build_context({"original_filename": "testbrief-scan.pdf", "source_kind": "upload"}, text)
    try:
        outcome = rules.apply_rules(rules.load_rules(), ctx)
        add("Regeln auswertbar", True, f"{len(outcome.matched)} Treffer", required=False)
    except Exception as exc:  # noqa: BLE001
        add("Regeln auswertbar", False, str(exc))
    tpl = appsettings.get("filename_template")
    add("Dateinamensvorlage", not naming.validate_template(tpl),
        naming.render(tpl, {"document_date": "2026-01-01", "sender": "Beispiel GmbH", "document_type": "Rechnung", "reference": "TEST-0001"}, "x.pdf", ".pdf"))
    folders = db.query("SELECT account_id, drive_id, path FROM drive_folders WHERE role IN ('archive','archive_root') LIMIT 5")
    if not folders:
        add("Archivordner freigegeben", False, "Noch kein Archivordner ausgewählt")
    for f in folders:
        try:
            services.drive(f["account_id"]).get(f["drive_id"], "id,name")
            add(f"Drive-Ordner erreichbar: {f['path']}", True)
        except ghttp.GoogleApiError as exc:
            add(f"Drive-Ordner erreichbar: {f['path']}", False, str(exc))
    provider = appsettings.get("ai_provider") or {}
    if provider.get("kind") not in (None, "none"):
        from .pipeline.processor import _provider_config
        from .ai import providers

        try:
            call = providers.analyze(_provider_config(), text or "Testbrief Rechnung TEST-0001", services.archive_folders(),
                                     {}, allow_external=bool(appsettings.get("allow_external_ai")))
            add("KI-Provider", True, f"{call.model}, {call.seconds:.1f}s", required=False)
        except providers.ProviderError as exc:
            add("KI-Provider", False, str(exc), required=False)
    ok = all(c["ok"] for c in checks if c["required"])
    return {"ok": ok, "checks": checks}

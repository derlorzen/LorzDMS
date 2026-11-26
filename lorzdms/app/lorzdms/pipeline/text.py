"""Textextraktion (pypdfium2) und lokale OCR (OCRmyPDF/Tesseract).

OCR läuft immer als separater Prozess mit Zeitlimit und niedriger CPU-Priorität. Das
Original wird nie verändert; OCRmyPDF schreibt ein Derivat in das Arbeitsverzeichnis.
"""

from __future__ import annotations

import functools
import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

MIN_CHARS_PER_PAGE = 40


@dataclass
class TextResult:
    text: str
    pages: list[str]
    method: str  # embedded | ocr | mixed | none
    page_count: int
    ocr_used: bool = False
    ocr_seconds: float | None = None
    derivative: Path | None = None
    warnings: list[str] = field(default_factory=list)


def extract_embedded(path: Path) -> list[str]:
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(str(path))
    pages: list[str] = []
    try:
        for i in range(len(pdf)):
            page = pdf[i]
            tp = page.get_textpage()
            try:
                pages.append(tp.get_text_range() or "")
            finally:
                tp.close()
                page.close()
    finally:
        pdf.close()
    return [p.replace("\r\n", "\n").replace("\r", "\n") for p in pages]


def needs_ocr(pages: list[str]) -> bool:
    if not pages:
        return True
    weak = sum(1 for p in pages if len(p.strip()) < MIN_CHARS_PER_PAGE)
    return weak > 0


class OcrUnavailable(RuntimeError):
    pass


class OcrFailed(RuntimeError):
    pass


def ocr_available() -> bool:
    return shutil.which("ocrmypdf") is not None and shutil.which("tesseract") is not None


@functools.lru_cache(maxsize=1)
def osd_available() -> bool:
    """Seitenausrichtung (--rotate-pages) braucht die Tesseract-Daten ``osd``."""
    try:
        out = subprocess.run(["tesseract", "--list-langs"], capture_output=True, timeout=30, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return False
    langs = (out.stdout + out.stderr).decode("utf-8", "replace").split()
    return "osd" in langs


def run_ocr(
    src: Path,
    workdir: Path,
    *,
    languages: str,
    timeout: int,
    is_image: bool,
    pdfa: bool = False,
    force: bool = False,
) -> tuple[Path, list[str], float]:
    if not ocr_available():
        raise OcrUnavailable("ocrmypdf/tesseract nicht installiert")
    out = workdir / "ocr.pdf"
    sidecar = workdir / "ocr.txt"
    cmd = [
        "ocrmypdf",
        "--language", languages,
        *(["--rotate-pages"] if osd_available() else []),
        "--deskew",
        "--jobs", "1",
        "--output-type", "pdfa" if pdfa else "pdf",
        "--sidecar", str(sidecar),
        "--quiet",
    ]
    cmd.append("--force-ocr" if force else "--skip-text")
    if is_image:
        cmd += ["--image-dpi", "300"]
    cmd += [str(src), str(out)]
    env = dict(os.environ, OMP_THREAD_LIMIT="1")
    started = time.monotonic()
    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            env=env,
            preexec_fn=(lambda: os.nice(10)) if hasattr(os, "nice") else None,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise OcrFailed(f"OCR-Zeitlimit von {timeout}s überschritten") from exc
    elapsed = time.monotonic() - started
    # Rückgabecode 6 = Seite hat bereits Text (bei --skip-text unkritisch), 10 = PDF/A-Warnung
    if proc.returncode not in (0, 6, 10) or not out.exists():
        err = proc.stderr.decode("utf-8", "replace")[-500:]
        raise OcrFailed(f"OCRmyPDF Rückgabecode {proc.returncode}: {err}")
    text = sidecar.read_text("utf-8", "replace") if sidecar.exists() else ""
    pages = text.split("\f")
    return out, pages, elapsed


def extract(
    path: Path,
    mime: str,
    workdir: Path,
    *,
    languages: str,
    timeout: int,
    force_ocr: bool = False,
) -> TextResult:
    is_image = mime.startswith("image/")
    warnings: list[str] = []
    embedded: list[str] = []
    if not is_image:
        embedded = extract_embedded(path)
        if not force_ocr and not needs_ocr(embedded):
            return TextResult("\n\f\n".join(embedded), embedded, "embedded", len(embedded))
    if not ocr_available():
        warnings.append("OCR nicht verfügbar – nur eingebetteter Text")
        method = "embedded" if any(p.strip() for p in embedded) else "none"
        return TextResult("\n\f\n".join(embedded), embedded, method, len(embedded), warnings=warnings)
    derivative, ocr_pages, seconds = run_ocr(
        path, workdir, languages=languages, timeout=timeout, is_image=is_image, force=force_ocr
    )
    # Mit --skip-text enthält der Sidecar für Seiten mit vorhandenem Text nur einen Hinweis;
    # daher seitenweise den besseren Text wählen.
    pages: list[str] = []
    count = max(len(embedded), len(ocr_pages))
    used_ocr = False
    for i in range(count):
        e = embedded[i] if i < len(embedded) else ""
        o = ocr_pages[i] if i < len(ocr_pages) else ""
        if "[OCR skipped on page" in o:
            o = ""
        if len(e.strip()) >= MIN_CHARS_PER_PAGE or len(o.strip()) <= len(e.strip()):
            pages.append(e)
        else:
            pages.append(o)
            used_ocr = True
    while pages and not pages[-1].strip() and len(pages) > max(len(embedded), 1):
        pages.pop()
    method = "ocr" if used_ocr and not any(p.strip() for p in embedded) else ("mixed" if used_ocr else "embedded")
    if not any(p.strip() for p in pages):
        warnings.append("Kein Text erkannt (leere Seite oder sehr schlechte Bildqualität)")
        method = "none"
    return TextResult(
        "\n\f\n".join(pages), pages, method, len(pages), ocr_used=used_ocr,
        ocr_seconds=seconds, derivative=derivative, warnings=warnings,
    )

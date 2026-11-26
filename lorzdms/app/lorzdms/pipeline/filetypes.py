"""Dateityp-Erkennung anhand des Inhalts (nicht der Endung) und Sicherheitsprüfung."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# Unterstützt in dieser Version. Weitere Formate (HEIC, DOCX, XLSX, EML, XML) folgen.
SUPPORTED = {
    "application/pdf": (".pdf",),
    "image/png": (".png",),
    "image/jpeg": (".jpg", ".jpeg"),
    "image/tiff": (".tif", ".tiff"),
}


def sniff(head: bytes) -> str | None:
    if head.startswith(b"%PDF-") or (b"%PDF-" in head[:1024]):
        return "application/pdf"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head[:4] in (b"II*\x00", b"MM\x00*"):
        return "image/tiff"
    if head.startswith(b"PK\x03\x04"):
        return "application/zip"
    if head[4:12] in (b"ftypheic", b"ftypheix", b"ftypmif1", b"ftyphevc"):
        return "image/heic"
    return None


@dataclass
class Validation:
    ok: bool
    mime: str | None
    reason: str = ""
    quarantine: bool = False


def validate(path: Path, original_name: str, max_bytes: int, max_pixels: int) -> Validation:
    size = path.stat().st_size
    if size == 0:
        return Validation(False, None, "Datei ist leer")
    if size > max_bytes:
        return Validation(False, None, f"Datei zu groß ({size} Bytes, Limit {max_bytes})")
    with path.open("rb") as fh:
        head = fh.read(2048)
    mime = sniff(head)
    if mime is None:
        return Validation(False, None, "Unbekannter oder nicht unterstützter Dateityp")
    if mime not in SUPPORTED:
        return Validation(False, mime, f"Dateityp {mime} wird noch nicht unterstützt")
    ext = Path(original_name).suffix.lower()
    if ext and ext not in SUPPORTED[mime]:
        # Inhalt und Endung widersprechen sich: möglicher Täuschungsversuch
        return Validation(False, mime, f"Endung {ext} passt nicht zum Inhalt {mime}", quarantine=True)
    if mime == "application/pdf":
        reason = _check_pdf(path)
        if reason:
            return Validation(False, mime, reason, quarantine=True)
    else:
        reason = _check_image(path, max_pixels)
        if reason:
            return Validation(False, mime, reason, quarantine=True)
    return Validation(True, mime)


def _check_pdf(path: Path) -> str:
    import pypdfium2 as pdfium

    try:
        pdf = pdfium.PdfDocument(str(path))
    except pdfium.PdfiumError as exc:
        msg = str(exc)
        if "password" in msg.lower():
            return "PDF ist passwortgeschützt"
        return f"PDF nicht lesbar: {msg[:200]}"
    try:
        if len(pdf) == 0:
            return "PDF enthält keine Seiten"
        if len(pdf) > 2000:
            return "PDF hat mehr als 2000 Seiten"
    finally:
        pdf.close()
    return ""


def _check_image(path: Path, max_pixels: int) -> str:
    from PIL import Image

    previous = Image.MAX_IMAGE_PIXELS
    Image.MAX_IMAGE_PIXELS = max_pixels
    try:
        with Image.open(path) as im:
            w, h = im.size
            if w * h > max_pixels:
                return f"Bild zu groß ({w}x{h})"
            im.verify()
    except Image.DecompressionBombError:
        return "Bild überschreitet das Pixel-Limit (Dekompressionsbombe?)"
    except Exception as exc:  # noqa: BLE001 – jede Pillow-Ausnahme bedeutet: unbrauchbar
        return f"Bild nicht lesbar: {type(exc).__name__}"
    finally:
        Image.MAX_IMAGE_PIXELS = previous
    return ""


def pdf_is_signed(path: Path) -> bool:
    """Erkennt digitale Signaturen (Signaturfeld mit /ByteRange). Konservativ: lieber
    falsch-positiv, damit signierte Originale nie durch Derivate ersetzt werden."""
    try:
        data = path.read_bytes()
    except OSError:
        return False
    return b"/ByteRange" in data and (b"/Sig" in data or b"/adbe.pkcs7" in data or b"/ETSI.CAdES" in data)

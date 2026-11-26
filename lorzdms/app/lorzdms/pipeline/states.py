"""Zustandsmaschine eines Dokuments.

Jeder Verarbeitungsschritt prüft den Ausgangszustand und setzt bei Erfolg den nächsten.
Ein Schritt, der erneut ausgeführt wird (Wiederanlauf), erkennt bereits erledigte Arbeit
(Idempotenz) anhand der gespeicherten Felder.
"""

from __future__ import annotations

NEW = "new"                    # erfasst, Quelle bekannt
FETCHED = "fetched"            # Datei liegt im temporären Arbeitsverzeichnis
VALIDATED = "validated"        # Typ/Größe geprüft, Hash berechnet
EXTRACTED = "extracted"        # Text vorhanden (eingebettet oder OCR)
ANALYZED = "analyzed"          # Regeln/KI ausgewertet, Entscheidung gespeichert
OBSERVED = "observed"          # Beobachtungsmodus: Entscheidung protokolliert, nichts verändert
NEEDS_REVIEW = "needs_review"  # wartet auf manuelle Prüfung
APPROVED = "approved"          # Ablage freigegeben (automatisch oder manuell)
ARCHIVING = "archiving"        # Drive-Operation läuft (pending im drive_operations-Journal)
ARCHIVED = "archived"          # Drive hat die Operation bestätigt
VERIFIED = "verified"          # zusätzlich per Metadatenabruf verifiziert
DONE = "done"                  # indexiert, temporäre Dateien bereinigt
DUPLICATE = "duplicate"        # identische Datei bereits vorhanden
EXCLUDED = "excluded"          # per Regel/Benutzer von der Verarbeitung ausgeschlossen
FAILED = "failed"              # endgültig fehlgeschlagen (Quelle bleibt unverändert)
QUARANTINED = "quarantined"    # Sicherheitsprüfung nicht bestanden

TERMINAL = {DONE, DUPLICATE, EXCLUDED, FAILED, QUARANTINED}

TRANSITIONS: dict[str, set[str]] = {
    NEW: {FETCHED, FAILED, DUPLICATE, EXCLUDED},
    FETCHED: {VALIDATED, QUARANTINED, FAILED, EXCLUDED, DUPLICATE},
    VALIDATED: {EXTRACTED, DUPLICATE, FAILED, EXCLUDED},
    EXTRACTED: {ANALYZED, FAILED, EXCLUDED},
    ANALYZED: {OBSERVED, NEEDS_REVIEW, APPROVED, EXCLUDED, FAILED},
    OBSERVED: {ANALYZED, NEEDS_REVIEW, APPROVED, EXCLUDED, EXTRACTED},
    NEEDS_REVIEW: {APPROVED, EXCLUDED, ANALYZED, EXTRACTED},
    APPROVED: {ARCHIVING, NEEDS_REVIEW, FAILED},
    ARCHIVING: {ARCHIVED, APPROVED, FAILED, NEEDS_REVIEW},
    ARCHIVED: {VERIFIED, ARCHIVING, FAILED},
    VERIFIED: {DONE},
    DONE: {NEEDS_REVIEW, EXTRACTED},  # Rückgängig / erneute Analyse
    DUPLICATE: {NEEDS_REVIEW, EXTRACTED},
    EXCLUDED: {NEEDS_REVIEW, EXTRACTED},
    FAILED: {NEW, FETCHED, VALIDATED, EXTRACTED, APPROVED, ARCHIVING, ARCHIVED},
    QUARANTINED: {EXCLUDED},
}


class InvalidTransition(RuntimeError):
    pass


def check(current: str, new: str) -> None:
    if new == current:
        return
    if new not in TRANSITIONS.get(current, set()):
        raise InvalidTransition(f"{current} -> {new} nicht erlaubt")

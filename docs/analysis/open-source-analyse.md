# Open-Source-Analyse

Stand: 2026-11-26. Alle Repositories wurden über die GitHub-API abgefragt und – soweit
öffentlich – geklont und im Quellcode gesichtet. Sterne/Aktivität sind Momentaufnahmen.

## Übersicht

| Projekt | Existiert | Lizenz | Letzter Push | Eignung für LorzDMS |
|---|---|---|---|---|
| appenz/papersort | ja | Apache-2.0 | 2026-10-21 | Ideengeber, einzelne Muster übernehmbar, **kein Fork** |
| robeertm/DocuSort | ja | **Source-Available, keine Ableitungen erlaubt** | 2026-11-26 | **nicht verwendbar** (nur Funktionsreferenz) |
| protocol/document-filing-automation | ja | keine Lizenz angegeben | 2026-05-11 | nur README (Architekturbeschreibung), kein Code |
| minimalmerlin/ai-document-sorter | ja | MIT | 2026-01-14 | klein, lokal (Ollama+Tesseract), Muster übernommen |
| RatnamOjha/AI-Drive-Organizer | ja | MIT | 2026-10-01 | Keyword-Klassifizierer, Drive mit Vollzugriff, Notebook-lastig |
| paperless-ngx/paperless-ngx | ja | GPL-3.0 | 2026-11-26 | funktionale Referenz (UI-Konzepte, Matching), kein Code-Import |
| ocrmypdf/OCRmyPDF | ja | MPL-2.0 | 2026-11-25 | **direkt genutzt** (als Programm/Bibliothek, unverändert) |
| tesseract-ocr/tesseract | ja | Apache-2.0 | 2026-11-26 | **direkt genutzt** (über OCRmyPDF) |
| n8n-io/n8n | ja | Sustainable Use License (fair-code) | 2026-11-26 | nur als externer Integrationspartner (Webhooks/REST) |
| home-assistant/addons-example | ja | Apache-2.0 | 2026-11-23 | **Vorlage** für App-Struktur und Build-Workflow |
| BenoitAnastay/paperless-home-assistant-addon | ja | MIT | 2026-11-26 | Referenz für s6-rc-Dienste, Ingress-Konfiguration |

## Einzelbewertung

### PaperSort (bevorzugter Ausgangspunkt)

- ~5 100 Zeilen Python, CLI + Textual-TUI, Storage-Treiber (lokal, Google Drive, Dropbox),
  LLM-Treiber (OpenAI, Mistral), Layout-Beschreibung als eingerückte Textdatei,
  Metadaten-Cache, Deduplizierung, Retry-Hilfen.
- Positiv: saubere Treiber-Abstraktion, `layout.txt`-Konzept (Ordnerbaum mit Beschreibung
  als Klassifizierungskontext), Retry mit exponentiellem Backoff, Ordner-Matching für
  Firmenordner.
- Ungeeignet als Fork-Basis:
  - kein Webserver, keine Datenbank, keine Job-Queue, keine Benutzer/Rechte;
  - Google Drive nur über **Service-Account** mit Scope `drive` (voll), kein OAuth für
    Privatkonten;
  - **kopiert** Dateien in das Archiv und **löscht** im `--ingest`-Modus anschließend die
    Quelle (`delete` → Papierkorb) – widerspricht der Vorgabe „verschieben statt kopieren
    und löschen, Datei-ID erhalten“;
  - keine Gmail-Anbindung, kein OCR (verlässt sich auf Vision-LLM bzw. vorhandenen Text);
  - externe LLM-API ist Pflicht.
- Entscheidung: **Neuentwicklung**, Übernahme der Konzepte „Ordnerbaum mit Beschreibungen
  als KI-Kontext“ und „Retry-Klassifizierung transienter HTTP-Fehler“. Es wurde kein Code
  wörtlich übernommen; sollte das später geschehen, ist der Apache-2.0-Hinweis in
  `THIRD_PARTY_NOTICES.md` zu ergänzen.

### DocuSort

- Großes Projekt (~20 000 Zeilen), funktional sehr nah am Ziel (OCR, KI-Ablage, Fristen,
  Fundstellen, Bridge, Tailscale).
- **Lizenz verbietet Änderungen, Ableitungen und Weitergabe.** Keine Übernahme von Code,
  Struktur oder Texten. Nur als Beleg genutzt, dass der Funktionsumfang realistisch ist.

### protocol/document-filing-automation

- Enthält nur README (+ DOCX), keine Implementierung, keine Lizenz.
- Nützliche, allgemein bekannte Konzepte bestätigt: Konfidenzschwellen mit
  Ausnahme-Warteschlange, Dateinamens-Engine, Audit-Log. Unabhängig umgesetzt.

### minimalmerlin/ai-document-sorter (MIT)

- Kleiner lokaler Ordner-Watcher: PDF-Text zuerst, sonst Tesseract, Ollama-Benennung.
- Bestätigt die Strategie „vorhandenen Text nutzen, OCR nur bei Bedarf“. Kein Code
  übernommen (zu einfach, kein Fehler-/Zustandsmodell).

### RatnamOjha/AI-Drive-Organizer (MIT)

- Keyword-JSON-Klassifizierer und Drive-Verschiebung mit Scope `drive`, InstalledAppFlow.
- Bestätigt: Verschieben über `addParents/removeParents` erhält die Datei-ID. Kein Code
  übernommen.

### Paperless-ngx (GPL-3.0)

- Funktionale Referenz für Dashboard, Dokumentenliste, Korrespondenten/Typen/Tags,
  Matching-Algorithmen („any/all/exact/regex/fuzzy/auto“), Workflows, Mail-Regeln.
- GPL-3.0 ist mit der gewählten Apache-2.0-Lizenz für eine Code-Übernahme nicht
  kompatibel (Einbettung würde LorzDMS unter GPL zwingen). Daher nur Konzepte.
- Architektur (PostgreSQL/Redis/Celery, lokales Originalarchiv) passt nicht zu den
  Vorgaben „Drive ist führend“ und „SQLite auf HAOS“.

### OCRmyPDF (MPL-2.0) und Tesseract (Apache-2.0)

- Werden **unverändert** genutzt (Alpine-Pakete im Container), Aufruf als separater
  Prozess mit Zeitlimit. MPL-2.0 erlaubt die Nutzung in Apache-2.0-Projekten, solange
  OCRmyPDF-Dateien selbst nicht verändert werden.
- Ghostscript (AGPL-3.0) wird von OCRmyPDF nur für PDF/A aufgerufen; es läuft als
  separates Programm und wird nicht gelinkt (Aggregation, siehe THIRD_PARTY_NOTICES).

### n8n

- Sustainable Use License → kein Bestandteil von LorzDMS. Anbindung ausschließlich über
  die REST-API und Webhooks von LorzDMS (Phase 6).

## Weitere Komponenten-Entscheidungen

| Bedarf | Gewählt | Lizenz | Begründung |
|---|---|---|---|
| PDF-Text & Seitenrender | pypdfium2 | Apache-2.0 / BSD-3 | PyMuPDF ist AGPL-3.0 und hätte die Lizenz des Gesamtprojekts bestimmt |
| Web-Framework | FastAPI, Starlette, Uvicorn | MIT / BSD-3 | Vorgabe, schlank |
| Validierung | Pydantic v2 | MIT | strukturierte KI-Ausgaben, API-Schemas |
| HTTP-Client | httpx | BSD-3 | Google- und KI-APIs direkt per REST, testbar mit MockTransport; spart die schweren google-api-python-client-Abhängigkeiten |
| Kryptografie | cryptography (Fernet/AES-GCM) | Apache-2.0 / BSD | Verschlüsselung von OAuth-Tokens |
| Datenbank | SQLite (WAL, FTS5) | Public Domain | Vorgabe HAOS, kein separater Dienst |
| Frontend | React, Vite, Tailwind CSS, shadcn/ui-Muster | MIT | Vorgabe |

## Home-Assistant-Vorgaben (geprüft am offiziellen Beispiel, Stand 2026-11-23)

- `repository.yaml` im Wurzelverzeichnis, je App ein Unterordner mit `config.yaml`,
  `Dockerfile`, `DOCS.md`, `README.md`, `CHANGELOG.md`, `icon.png`, `logo.png`,
  `translations/*.yaml`, optional `apparmor.txt`.
- Das aktuelle Beispiel nutzt **keine `build.yaml` mehr**: Basis-Image steht als
  `ARG BUILD_FROM=ghcr.io/home-assistant/base:3.23` im Dockerfile, Multi-Arch-Builds laufen
  über `home-assistant/builder`-Actions. LorzDMS folgt dem aktuellen Stand; eine
  `build.yaml` wird daher bewusst **nicht** angelegt (siehe ADR 0001).
- Ingress-Anfragen kommen ausschließlich vom Supervisor-Proxy `172.30.32.2` und tragen
  `X-Ingress-Path` sowie `X-Remote-User-Id/-Name/-Display-Name`.

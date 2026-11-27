# Roadmap

Legende: ✅ umgesetzt und getestet · 🟡 teilweise · ⬜ offen

Die Phasen folgen dem Auftrag; die Home-Assistant-App hat Vorrang vor Coolify.

## Phase 1 – Technische Grundlage
- ✅ Open-Source-Analyse (`docs/analysis/open-source-analyse.md`)
- ✅ Architekturentscheidung (`docs/adr/0001-architektur.md`)
- ✅ HA-App-Repository-Struktur (`repository.yaml`, `lorzdms/config.yaml`, Dockerfile, s6-rc)
- ✅ SQLite WAL, Migrationen, FTS5
- ✅ Persistente Job-Queue mit Retry, Lease und Dead-Letter
- ✅ Ingress-Authentifizierung mit Supervisor-Prüfung, Rollen
- ✅ Weboberfläche über Ingress (Übersicht, Prüfung, Dokumente, Quellen, Ordner, Regeln, Einstellungen); Englisch nur teilweise übersetzt
- ✅ Setup-Assistent (Administrator, Systemprüfung, Google, Ordner, Quellen, KI, Regeln, Testlauf, Aktivierung)
- 🟡 Container-Build für amd64/aarch64 (CI baut das Image; Installation auf echter HAOS-Instanz noch nicht getestet)
- ⬜ Vorgefertigte Images in GHCR (derzeit baut der Supervisor lokal)

## Phase 2 – Dokumentenimport
- ✅ Lokaler Eingang `/share/lorzdms/inbox`
- ✅ Manueller Upload (Weboberfläche, REST)
- ✅ Google Drive Eingangsordner (REST-Client, gegen Mock getestet)
- ✅ Gmail lesend (History-API + Suche, Anhangsfilter, gegen Mock getestet)
- ⬜ OCR-Konfidenzwert, PDF/A-Ausgabe in der Oberfläche, Ablage von OCR-Derivaten zusätzlich zum Original
- ✅ Textextraktion (pypdfium2), OCR (OCRmyPDF/Tesseract, lokal)
- ✅ SHA-256, Duplikate (Hash, Gmail-Message-/Attachment-ID, Drive-ID)
- ✅ Verarbeitungsjournal und Zustandsmaschine
- ⬜ Drive Changes-API und Push-Benachrichtigungen (derzeit Polling per Ordnerauflistung)
- ⬜ IMAP, WebDAV
- ⬜ Gmail Pub/Sub (Polling über History-API ist umgesetzt)
- ⬜ HEIC, DOCX, XLSX, EML, ZUGFeRD/XRechnung

## Phase 3 – Intelligente Ablage
- ✅ Regel-Engine (UND/ODER, Regex, Prioritäten, Testlauf)
- ✅ KI-Provider-Schnittstelle: Ollama, OpenAI-kompatibel, Anthropic (validiertes JSON)
- ✅ Dateinamensvorlagen
- ✅ Konfidenzschwellen, manuelle Prüfung, Bestätigen/Korrigieren
- ✅ Rückgängig-Funktion für Verschiebungen
- ⬜ Visueller Regel-Editor (derzeit JSON-Editor mit Testlauf)
- ⬜ Gemini, Mistral, Azure als eigene Adapter (über OpenAI-kompatible Endpunkte nutzbar)

## Phase 4 – Dokumentenmanagement
- ✅ Volltextsuche (FTS5)
- ⬜ Import bestehender Drive-Archive (Dry-Run), Lernfunktion, Embeddings, Assistent

## Phase 5 – Erweiterte Funktionen
- ✅ Vorgänge, Fristen, Erinnerungen über Home Assistant, Tags (0.2.0)
- ⬜ Berichte (19 Uhr), Kalender, IMAP, WebDAV

## Phase 6 – Integrationen
- ⬜ HACS-Integration `custom_components/lorzdms`, Dashboard, Blueprints
- ⬜ MCP-Server (standardmäßig deaktiviert), Webhooks

## Phase 7 – Produktionsreife
- ⬜ Sicherheitsaudit, ARM64-Tests auf HAOS, Coolify-Deployment, Performance

## Migration des bestehenden Gmail-PDF-Imports
Die bestehende Lösung auf ha.lorzen.de bleibt unangetastet. LorzDMS startet im Modus
`processing_mode: observe` (nur lesen, nichts in Drive verändern). Umstellung erst nach
Abgleich und ausdrücklicher Freigabe (siehe `lorzdms/DOCS.md`, Abschnitt Migration).

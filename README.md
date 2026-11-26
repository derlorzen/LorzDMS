# LorzDMS

Selbst gehostetes, KI-gestütztes Dokumentenmanagement mit **Google Drive als führendem Archiv**.
Primäre Zielplattform ist eine **native Home-Assistant-App** (HAOS, amd64/aarch64, Ingress).

> Stand: **0.1.0 – Vorabversion (Phase 1/2 der Roadmap)**. Was funktioniert und was fehlt,
> steht unten und in [ROADMAP.md](ROADMAP.md). Nicht umgesetzte Funktionen sind dort als ⬜ markiert.

## Installation in Home Assistant

Einstellungen → Apps → App Store → ⋮ → Repositories → `https://github.com/derlorzen/LorzDMS`
→ „LorzDMS“ installieren → starten → in Seitenleiste anzeigen. Details: [INSTALLATION.md](INSTALLATION.md)
und [lorzdms/DOCS.md](lorzdms/DOCS.md).

## Umgesetzt (0.1.0)

| Bereich | Stand |
|---|---|
| Quellen | Gmail **nur lesend** (Suche + History-API, Anhangsfilter, Inline-/Logo-Ausschluss), Drive-Eingangsordner (Polling, optional rekursiv), `/share/lorzdms/inbox`, Upload (Drag & Drop, Mehrfach, Smartphone-Kamera), REST |
| Verarbeitung | Zustandsmaschine + Journal, Inhalts-basierte Typprüfung, Quarantäne, SHA-256-/Text-Duplikate, pypdfium2-Text, lokale OCR (Deskew, Rotation), signierte PDFs werden nie durch Derivate ersetzt |
| Ablage | Regel-Engine (UND/ODER/NICHT, Regex, Prioritäten, Testlauf), KI optional (Ollama, OpenAI-kompatibel, Anthropic) mit validiertem JSON, Dateinamensvorlagen, Konfliktauflösung, Drive-Schreibschutz, Verschieben mit Erhalt der Datei-ID, Upload-Verifikation (MD5), Rückgängig |
| Betrieb | SQLite WAL + FTS5, persistente Job-Queue (Retry, Lease, Dead-Letter), Ressourcenschutz, Backup-Snapshot, Ingress-Auth mit Rollen, CSRF-Schutz |
| Oberfläche | Übersicht, Prüfung (Stapel), Dokumente/Suche, Quellen, Ordner (Drive-Browser), Regeln (JSON-Editor), Einstellungen, Einrichtungsassistent, Dark Mode (folgt HA) |

Nicht umgesetzt (Auswahl): Vorgänge, Fristen, Berichte (19-Uhr-Bericht), Benachrichtigungen,
HACS-Integration und Dashboard, MCP-Server, IMAP, WebDAV, semantische Suche/Embeddings,
Lernfunktion, grafischer Regel-Editor, Coolify-Deployment, Drive-Changes-API/Push, Gmail Pub/Sub.

## Entwicklung

```bash
cd lorzdms/app
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt      # OCR-Tests brauchen zusätzlich tesseract (deu, eng)
pytest

cd ../frontend && npm ci && npm run build   # schreibt nach lorzdms/app/lorzdms/static
```

Lokaler Start ohne Home Assistant (nur Entwicklung):

```bash
export LORZDMS_DATA_DIR=/tmp/lorzdms LORZDMS_SHARE_DIR=/tmp/lorzdms-share LORZDMS_DEV_USER=dev
python -m lorzdms.maintenance init
python -m uvicorn --factory lorzdms.api.app:app_factory --host 127.0.0.1 --port 8099 &
python -m lorzdms.worker
```

`LORZDMS_DEV_USER` gilt nur für Anfragen von 127.0.0.1 und darf in Produktion nicht gesetzt sein.

## Dokumente

[ARCHITECTURE.md](ARCHITECTURE.md) · [SECURITY.md](SECURITY.md) · [PRIVACY.md](PRIVACY.md) ·
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) · [Open-Source-Analyse](docs/analysis/open-source-analyse.md) ·
[ADR 0001](docs/adr/0001-architektur.md) · [CHANGELOG](lorzdms/CHANGELOG.md)

Lizenz: Apache-2.0

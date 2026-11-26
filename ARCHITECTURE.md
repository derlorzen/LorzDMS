# Architektur

Entscheidungen und Begründungen: [docs/adr/0001-architektur.md](docs/adr/0001-architektur.md).

```
Home Assistant (Ingress, Supervisor-Proxy 172.30.32.2)
          │  X-Ingress-Path, X-Remote-User-*
          ▼
┌────────────────────────── LorzDMS-Container (s6-overlay) ──────────────────────────┐
│ init-lorzdms (oneshot): Verzeichnisse, Snapshot-Wiederherstellung, Migrationen      │
│ lorzdms-web  (Uvicorn/FastAPI): REST-API /api/*, Weboberfläche, Auth, Rollen          │
│ lorzdms-worker: Scheduler + Job-Queue → Pipeline (OCR als Kindprozess, nice 10)       │
│                                                                                     │
│ /data/database/lorzdms.sqlite3 (WAL, FTS5)   /data/secrets/master.key (0600)         │
│ /data/temp/doc-<id>/  (Arbeitskopien bis zur Verifikation)   /data/cache, quarantine │
└─────────────────────────────────────────────────────────────────────────────────────┘
        │ gmail.readonly                         │ drive (nur freigegebene Ordner)
        ▼                                        ▼
      Gmail                                 Google Drive (führendes Archiv)
```

## Pipeline (`lorzdms/app/lorzdms/pipeline/processor.py`)

`new → fetched → validated → extracted → analyzed → (observed | needs_review | approved)
→ archiving → archived → verified → done`, Nebenzustände `duplicate`, `excluded`,
`failed`, `quarantined`. Übergänge sind in `pipeline/states.py` festgelegt.

| Schritt | Idempotenz / Sicherheit |
|---|---|
| fetch | Arbeitskopie nur, wenn noch nicht vorhanden; Drive-Download mit MD5-Abgleich |
| validate | Typ nach Inhalt, Endung muss passen, Pixel-/Seiten-/Größenlimits, Quarantäne |
| extract | eingebetteter Text, OCR nur für Seiten ohne Text; Zeitlimit; Text-Hash für ähnliche Scans |
| analyze | Regeln vor KI; KI ohne Werkzeuge, JSON-Schema-Validierung, Ordner nur aus Freigabeliste |
| archive | `drive_operations`-Eintrag **vor** der Operation; Upload mit `appProperties.lorzdms_doc` → Wiederanlauf erkennt bereits hochgeladene Dateien |
| verify | Elternordner, nicht im Papierkorb, MD5 |
| finish | Index, lokale Quelle → `processed/`, Arbeitskopie löschen |

## Job-Queue (`jobqueue.py`)

SQLite-Tabelle `jobs`; Claim per `BEGIN IMMEDIATE`; Lease mit Ablauf; Backoff 30 s · 2^n
(max. 1 h, Jitter); `dead` nach `max_attempts`; `dedupe_key` (partieller Unique-Index).

## Migration auf PostgreSQL

SQLite-spezifisch sind FTS5 (`documents_fts`, Suche in `api/app.py`), der partielle
Unique-Index und `BEGIN IMMEDIATE`. Ein Adapter müsste diese durch `tsvector`/`SKIP LOCKED`
ersetzen. Noch nicht umgesetzt.

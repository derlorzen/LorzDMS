# ADR 0001 – Grundarchitektur

Status: angenommen (2026-11-26)

## Kontext

LorzDMS läuft primär als Home-Assistant-App auf einem HAOS-Rechner neben Home Assistant.
Die Stabilität von Home Assistant hat Vorrang. Google Drive ist das führende Archiv,
Gmail wird strikt lesend angebunden. Eine Coolify-Installation ist optional.

## Entscheidungen

1. **Neuentwicklung statt Fork.** Siehe `docs/analysis/open-source-analyse.md`.
   OCRmyPDF und Tesseract werden unverändert genutzt.

2. **Ein Container, zwei überwachte Prozesse (s6-overlay v3, `s6-rc.d`).**
   - `lorzdms-web`: Uvicorn/FastAPI, liefert API und gebaute React-Oberfläche über Ingress.
   - `lorzdms-worker`: Job-Worker plus Scheduler (Thread) – führt OCR, KI-Aufrufe und
     Synchronisierungen aus. OCR läuft als Kindprozess mit Zeitlimit, niemals im
     Home-Assistant-Core.
   - Weitere Worker sind optional (`worker_concurrency`), Standard ist ein OCR-Slot.

3. **SQLite im WAL-Modus** unter `/data/database/lorzdms.sqlite3`, FTS5 für Volltext.
   Migrationen als nummerierte SQL-Dateien (`lorzdms/migrations/NNNN_*.sql`), angewendet
   beim Start, Version in `schema_migrations`. SQLite-spezifische Teile (FTS5, `RETURNING`)
   sind auf das Modul `db.py`/`search.py` beschränkt, damit ein späterer PostgreSQL-Adapter
   möglich bleibt.

4. **Persistente Job-Queue in SQLite** (`jobs`-Tabelle): Priorität, `run_after`,
   Lease mit Ablaufzeit (Wiederaufnahme nach Absturz), exponentieller Backoff mit Jitter,
   Dead-Letter-Status `dead`. Eindeutiger `dedupe_key` verhindert doppelte Jobs.

5. **Verarbeitungsjournal + Zustandsmaschine pro Dokument.** Jeder Schritt ist idempotent,
   schreibt ein Journal-Ereignis und setzt den Zustand nur bei Erfolg weiter. Erlaubte
   Übergänge sind in `pipeline/states.py` festgelegt und werden geprüft.

6. **Drive-Schreibschutz.** Jede Schreiboperation läuft über `DriveGuard`, der prüft, dass
   das Ziel unterhalb eines ausdrücklich freigegebenen Archivordners liegt. Löschen ist
   nicht implementiert (es gibt keine Methode dafür). Dateien aus einem Drive-Eingang
   werden **verschoben** (`addParents`/`removeParents`, Datei-ID bleibt erhalten), lokale
   Dateien werden hochgeladen und über `md5Checksum` und Größe verifiziert.

7. **Gmail strikt lesend.** Scope `gmail.readonly`; der Client besitzt nur lesende Methoden.
   Ein Test stellt sicher, dass keine schreibenden Endpunkte angesprochen werden.

8. **Google OAuth ohne öffentliche Oberfläche.** Standard ist der Loopback-Fluss mit PKCE
   (`http://127.0.0.1:<port>/oauth2callback`, von Google für Desktop- und Web-Clients
   unterstützt): Nach der Zustimmung kopiert man die Adresszeile aus dem Browser in
   LorzDMS. Optional kann eine stabile HTTPS-Callback-URL konfiguriert werden, die nur
   den einen Callback-Pfad bereitstellt. OOB wird nicht verwendet.

9. **Authentifizierung über Ingress.** Identitätsheader werden nur akzeptiert, wenn die
   Verbindung vom Supervisor-Proxy (`172.30.32.2`) kommt. Der erste Benutzer, der den
   Einrichtungsassistenten abschließt, wird LorzDMS-Administrator; alle weiteren
   HA-Benutzer haben ohne Freigabe keinen Zugriff. Eigene Rollen (`admin`, `editor`,
   `viewer`) werden serverseitig geprüft.

10. **KI ist optional.** Reihenfolge: deterministische Regeln → (optional) KI-Provider.
    Ohne KI werden Dokumente erfasst, OCR-verarbeitet, durchsuchbar gemacht und per Regel
    abgelegt; sonst landen sie in der manuellen Prüfung. Externe Provider erfordern die
    ausdrückliche Freigabe `allow_external_ai`. KI-Ausgaben sind validiertes JSON ohne
    Tool-Zugriff; daraus abgeleitete Aktionen prüft die deterministische Schicht.

11. **Originale bleiben unverändert.** OCR erzeugt höchstens ein Derivat. Für signierte
    PDFs (Signaturfeld/`/ByteRange`) wird nie ein Derivat archiviert, nur der Textindex.
    Strategie konfigurierbar: `original_only` (Standard), `original_plus_derivative`,
    `derivative_only` (nur für unsignierte Scans).

12. **Keine `build.yaml`.** Das offizielle Beispiel (Stand 2026-11) setzt das Basis-Image im
    Dockerfile (`ARG BUILD_FROM`) und baut über `home-assistant/builder`-Actions. Bis die
    Images in GHCR veröffentlicht sind, baut der Supervisor lokal aus dem Dockerfile.

## Folgen

- Kein Redis/PostgreSQL nötig; der Speicherbedarf bleibt klein.
- Ein späterer PostgreSQL-Betrieb erfordert einen Adapter für Queue-Claim und FTS.
- OCR-Durchsatz ist bewusst begrenzt (Schutz von Home Assistant).

# LorzDMS – Dokumentation

LorzDMS erfasst Dokumente, erkennt ihren Inhalt lokal per OCR, klassifiziert sie per Regeln
(und optional KI) und legt sie in Ihren **bestehenden Google-Drive-Ordnern** ab. Google Drive
bleibt das führende Archiv; lokal speichert LorzDMS nur Datenbank, Texte, Suchindex,
Einstellungen und verschlüsselte Zugangsdaten.

> **Status 0.1.0 (Vorabversion).** Kern-Pipeline, Gmail/Drive/Upload/lokaler Eingang, OCR,
> Regeln, KI-Schnittstelle, Prüfung und Rückgängig sind umgesetzt und automatisiert getestet
> (gegen eine Nachbildung der Google-APIs). Noch **nicht** umgesetzt: Vorgänge, Fristen,
> Berichte, Benachrichtigungen, HACS-Integration, MCP-Server, IMAP, WebDAV, semantische Suche,
> grafischer Regel-Editor. Siehe `ROADMAP.md` im Repository.

## Installation

1. Einstellungen → Apps → App Store → ⋮ → Repositories → `https://github.com/derlorzen/LorzDMS` hinzufügen.
2. „LorzDMS“ auswählen → Installieren. Der Supervisor baut das Image lokal (einige Minuten).
3. Starten, „In Seitenleiste anzeigen“ aktivieren, LorzDMS öffnen.
4. Der Einrichtungsassistent führt durch die weiteren Schritte.

Die Seitenleiste ist nur für Home-Assistant-Administratoren sichtbar. Der erste Benutzer, der
LorzDMS öffnet, wird LorzDMS-Administrator. Weitere Benutzer erhalten erst nach Freigabe
(Einstellungen → Benutzer) Zugriff; Rollen: Lesen, Prüfen, Administrator.

## Google verbinden

LorzDMS benötigt einen eigenen OAuth-Client in Ihrem Google-Cloud-Projekt. Ein bestehendes
Projekt (z. B. das Ihres bisherigen Gmail-Imports) kann verwendet werden.

1. In der Google Cloud Console **Google Drive API** und **Gmail API** aktivieren.
2. OAuth-Zustimmungsbildschirm (Extern) einrichten, eigene Adresse als Testnutzer.
3. OAuth-Client-ID vom Typ **Desktop-App** anlegen und die JSON-Datei herunterladen.
   (Ein vorhandener Client vom Typ *Webanwendung* funktioniert ebenfalls, wenn
   `http://127.0.0.1:8765/oauth2callback` als Weiterleitungs-URI eingetragen wird.)
4. In LorzDMS → Einrichtung die JSON-Datei hochladen und „Google-Konto verbinden“ wählen.
5. Nach der Zustimmung leitet Google auf `http://127.0.0.1:8765/…` weiter. Diese Seite lädt
   nicht – das ist beabsichtigt. Die **vollständige Adresse aus der Adresszeile** kopieren und
   in LorzDMS einfügen.

Warum so? Ingress-Pfade sind dynamisch und nicht öffentlich erreichbar; Google verlangt aber
eine feste Weiterleitungsadresse. Der Loopback-Ablauf mit PKCE ist das von Google für
installierte Anwendungen vorgesehene Verfahren und erfordert keine öffentlich erreichbare
Oberfläche. Das veraltete OOB-Verfahren wird nicht verwendet.

**Berechtigungen:** Gmail ausschließlich `gmail.readonly`. Für Drive ist `drive` (Vollzugriff)
nötig, um bestehende Ordner zu lesen und Dateien darin zu verschieben; `drive.file` ist wählbar,
erlaubt aber nur von LorzDMS selbst angelegte Dateien. LorzDMS schreibt dennoch **nur** in
Ordner, die Sie unter „Ordner“ freigeben, und löscht nie Dateien.

**Testmodus:** Solange der Zustimmungsbildschirm im Status „Test“ ist, laufen Refresh-Tokens
nach 7 Tagen ab. LorzDMS zeigt dann „Neuanmeldung nötig“; Dokumente gehen nicht verloren.
Für Dauerbetrieb den Status auf „In Produktion“ setzen.

## Ordner und Quellen

- **Archiv (Wurzel)**: z. B. `Dokumente/`. Bestehende Unterordner werden lesend übernommen und
  stehen als Ablageziele zur Verfügung. Eine Beschreibung je Ordner verbessert die KI-Zuordnung.
- **Eingang**: wird nur gelesen; Dateien daraus werden nach verifizierter Ablage verschoben
  (Datei-ID bleibt erhalten). Eingangsordner sind nie Ablageziel.
- **Manuelle Prüfung**: optionaler Ordner, z. B. für die Rückgängig-Funktion bei Uploads.
- **Lokaler Eingang**: `/share/lorzdms/inbox` (z. B. Scanner, Samba-App). Nach erfolgreicher
  Ablage wird die Datei nach `/share/lorzdms/processed` verschoben.

## Verarbeitungsmodi

| Modus | Verhalten |
|---|---|
| Beobachten (Standard) | analysiert, protokolliert, verändert nichts in Google Drive |
| Bestätigen | jede Ablage muss in „Prüfung“ bestätigt werden |
| Automatisch | Ablage ab Schwellenwert (Standard 95 %); erst nach erfolgreichem Testlauf wählbar |

Regeln ergeben Konfidenz 100 %. Reine KI-Entscheidungen werden standardmäßig auf 94 %
begrenzt und daher immer zur Bestätigung vorgelegt, bis Sie die Schwellen anhand realer
Ergebnisse überprüft haben.

## Migration des bestehenden Gmail-PDF-Imports

Ihr bisheriger Import bleibt unverändert aktiv. Empfohlenes Vorgehen:

1. LorzDMS im Modus **Beobachten** mit Gmail-Quelle betreiben (parallel zum alten Import).
2. Den Drive-Ordner, in den der alte Import schreibt, als **Eingang** hinzufügen. Doppelt
   erfasste Anhänge erkennt LorzDMS über die SHA-256-Prüfsumme als Duplikat.
3. Vorschläge in „Prüfung“ kontrollieren, Regeln ergänzen, dann auf **Bestätigen** umstellen.
4. Erst wenn die Ergebnisse überzeugen, entscheiden Sie selbst, den alten Import abzuschalten.
   LorzDMS deaktiviert oder verändert ihn nie.

## Optionen

| Option | Bedeutung |
|---|---|
| `ocr_languages` | Tesseract-Sprachen (`deu+eng`) |
| `ocr_timeout_seconds` | Zeitlimit je Dokument |
| `max_file_size_mb` | Größenlimit |
| `min_free_disk_mb` | Verarbeitung pausiert unterhalb dieses freien Speichers |
| `max_load_per_cpu` | Bei höherer Systemlast werden Dokumente zurückgestellt |
| `processing_window` | Zeitfenster für Massenimporte (z. B. `22:00-06:00`) |
| `local_inbox_enabled` | `/share/lorzdms/inbox` überwachen |
| `oauth_redirect_uri` | Weiterleitungsadresse für Google OAuth |

OCR läuft mit genau einem Prozess, niedriger CPU-Priorität und Zeitlimit. Bei hoher Last,
wenig Arbeitsspeicher oder wenig freiem Speicher werden Dokumente zurückgestellt.

## Backup

LorzDMS ist in Home-Assistant-Backups enthalten (Datenbank als konsistenter Snapshot,
Einstellungen, Regeln, verschlüsselte Zugangsdaten samt Schlüssel, Journal, unfertige Importe;
ohne Cache). Nach einer Wiederherstellung wird die Datenbank beim Start aus dem Snapshot
erzeugt.

**Wichtig:** Das Home-Assistant-Backup sichert **nicht** Ihr Google-Drive-Archiv. Sichern Sie
Google Drive separat (z. B. Google Takeout).

## Datenschutz

Dokumenteninhalte verlassen den Rechner nur, wenn Sie einen externen KI-Provider einrichten
**und** „Externe KI-Provider erlauben“ aktivieren. Protokolle enthalten keine Dokumenteninhalte.
Siehe `PRIVACY.md` und `SECURITY.md` im Repository.

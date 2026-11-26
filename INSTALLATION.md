# Installation

## Home Assistant OS (empfohlen)

1. **Repository hinzufügen:** Einstellungen → Apps → App Store → ⋮ (oben rechts) → Repositories →
   `https://github.com/derlorzen/LorzDMS` → Hinzufügen.
2. **Installieren:** „LorzDMS“ öffnen → Installieren. In Version 0.1.0 baut der Supervisor das
   Image lokal aus dem Dockerfile (vorgefertigte Images folgen; siehe ROADMAP).
3. **Starten** und „In Seitenleiste anzeigen“ aktivieren. Optional „Watchdog“ aktivieren.
4. **Einrichtung** in LorzDMS durchlaufen (Google-Client, Konto, Ordner, Quellen, Testlauf, Modus).

Keine SSH-, Terminal- oder Docker-Compose-Schritte nötig. Der Webserver lauscht nur im internen
Docker-Netz (Port 8099, nicht veröffentlicht) und ist ausschließlich über Ingress erreichbar.

### Scanner / Samba

Mit der offiziellen Samba-App ist `share/lorzdms/inbox` im Netzwerk erreichbar. Dateien, die dort
abgelegt werden, verarbeitet LorzDMS automatisch (nach ca. 30 Sekunden Stabilitätsprüfung).

## Updates

Neue Versionen erscheinen im App Store als Update. Datenbankmigrationen laufen beim Start
automatisch. Vor Updates empfiehlt Home Assistant ein Backup (LorzDMS unterstützt das).

## Coolify / Docker Compose

Noch **nicht umgesetzt** (Roadmap Phase 7). Die Anwendung ist so aufgebaut, dass sie ohne
Supervisor laufen kann (Konfiguration über `LORZDMS_*`-Umgebungsvariablen), aber eine
abgesicherte Authentifizierung ohne Ingress fehlt noch. Bitte bis dahin nicht öffentlich betreiben.

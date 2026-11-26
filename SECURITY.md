# Sicherheit

## Melden von Schwachstellen

Bitte nicht öffentlich als Issue, sondern über „Security → Report a vulnerability“ im GitHub-Repository.

## Umgesetzte Maßnahmen (0.1.0)

- **Zugriff nur über Ingress**: Identitätsheader werden nur von `172.30.32.2` (Supervisor) akzeptiert;
  kein veröffentlichter Port. Seitenleiste nur für HA-Administratoren (`panel_admin`).
- **Eigene Rollen** (kein Zugriff / Lesen / Prüfen / Administrator), serverseitig geprüft; neue
  HA-Benutzer haben standardmäßig keinen Zugriff. Dokumente mit Sichtbarkeit „admins“ sind für
  andere Rollen in Liste, Detail, Datei, Text und Suche unsichtbar (IDOR-Test vorhanden).
- **CSRF**: schreibende Anfragen benötigen `X-Requested-With: lorzdms` (erzwingt CORS-Preflight).
- **CSP** ohne Inline-Skripte; Dateiauslieferung mit eigener restriktiver CSP; `nosniff`, `no-referrer`.
- **Geheimnisse**: OAuth-Tokens, Client-Secret und API-Keys mit Fernet (AES-128-CBC + HMAC)
  verschlüsselt; Schlüssel in `/data/secrets/master.key` (0600). Keine Geheimnisse in Logs oder API-Antworten.
- **OAuth**: PKCE (S256), einmaliger `state` (15 min), keine schreibenden Gmail-Scopes (werden abgelehnt).
- **Drive**: Schreibschutz auf freigegebene Ordner, Eingangsordner nie Ziel, keine Löschfunktion im Code.
- **Uploads**: Größenlimit, Typprüfung nach Inhalt, Endungs-Abgleich, Pixel-Limit (Dekompressionsbomben),
  Seitenlimit, Quarantäne.
- **OCR** als Kindprozess mit Zeitlimit und niedriger Priorität.
- **Prompt-Injection**: Dokumenttext als markierte, nicht vertrauenswürdige Daten; Modell ohne Werkzeuge;
  Ausgabe gegen Schema validiert; Ordner nur aus Freigabeliste; Aktionen nur über deterministische Schicht.
- **SSRF**: KI-URLs gegen Metadaten- und Supervisor-Netze gesperrt; externe Ziele nur per HTTPS.
- **Audit-Log** für sicherheitsrelevante Aktionen (ohne Dokumenteninhalte).
- Container ohne Privilegien, ohne Docker-Socket, ohne Host-Netz; nur `/share` gemappt.

## Bekannte Einschränkungen / offen

- Container läuft als root (Standard der HA-Base-Images); Wechsel auf unprivilegierten Benutzer offen.
- Kein eigenes AppArmor-Profil.
- ClamAV, Passkeys, TOTP (für Zugriff ohne Ingress) noch nicht umgesetzt.
- Sicherheitsaudit gemäß Phase 7 steht aus.

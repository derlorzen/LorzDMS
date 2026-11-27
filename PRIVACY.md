# Datenschutz

## Lokal gespeichert (`/data`)

Datenbank mit Metadaten, extrahierten Texten, Suchindex, Regeln, Entscheidungen, Journal,
verschlüsselten Zugangsdaten; temporäre Arbeitskopien bis zur verifizierten Ablage;
Vorschau-Cache (nicht im Backup).

## Externe Datenübermittlungen

| Empfänger | Wann | Daten |
|---|---|---|
| Google (Drive, Gmail, OAuth) | immer, sobald verbunden | API-Abrufe; Upload/Verschieben nur in freigegebene Ordner |
| Externer KI-Provider (OpenAI, Anthropic, …) | **nur** wenn eingerichtet **und** „Externe KI-Provider erlauben“ aktiv | Dokumenttext (max. 24 000 Zeichen), Dateiname, Betreff, Absenderadresse, Ordnerliste |
| Lokaler KI-Server (Ollama im Heimnetz) | wenn eingerichtet | wie oben, verlässt das lokale Netz nicht |
| Home Assistant (lokal, über den Supervisor) | wenn Fristen-Erinnerungen aktiv sind | Titel und Fälligkeitsdatum der Frist; bei `notify.*`-Diensten leitet Home Assistant die Nachricht ggf. an die Companion-App weiter |

Jede KI-Analyse wird im Journal des Dokuments mit Provider und Modell protokolliert.

## Protokolle

Systemprotokolle enthalten Dokument-IDs und Schritte, keine Dokumenteninhalte.

## Löschen

Noch nicht umgesetzt: konfigurierbare Aufbewahrungsfristen sowie Export-/Löschfunktion für
personenbezogene Daten (Roadmap). Deinstallation der App entfernt alle lokalen Daten; das
Drive-Archiv bleibt unberührt.

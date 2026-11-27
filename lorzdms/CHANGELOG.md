# Changelog

## 0.2.0 – 2026-11-27

- **Fristen und Erinnerungen**: Fälligkeitsdaten und erkannte Fristen (Zahlung, Kündigung, Widerspruch, Antwort, Termin, Wiedervorlage) werden bei der Analyse als Fristen übernommen; berechnete Fristen sind als „bitte prüfen“ markiert. Fristen lassen sich manuell anlegen, erledigen, verwerfen und verschieben. Verworfene Fristen tauchen bei erneuter Analyse nicht wieder auf.
- Erinnerungen über Home Assistant (`persistent_notification.create` oder `notify.<dienst>`): eine am Vorlauftag (Standard 3 Tage), eine am Fälligkeitstag, frühestens ab einer einstellbaren Uhrzeit. Übertragen werden nur Titel und Datum der Frist. Dafür braucht die App jetzt die Berechtigung `homeassistant_api`.
- **Vorgänge**: bündeln Dokumente und Fristen. Mit einer Referenz (Aktenzeichen, Vertrags-, Versicherungs- oder Kundennummer) werden neue Dokumente automatisch einem offenen Vorgang zugeordnet.
- **Tags**: in der Dokumentansicht bearbeiten, Dokumente nach Tag filtern, Tags umbenennen, zusammenführen und entfernen.
- Übersicht zeigt überfällige und anstehende Fristen.
- Beim Update werden künftige Fälligkeitsdaten und Fristen aus bereits analysierten Dokumenten einmalig übernommen; vergangene nicht.

## 0.1.7 – 2026-11-27

- Nativer OpenRouter-Provider für Perplexity Decider v1.3 (free): Ordnerklassifizierung, Dokumenttyp und Vertraulichkeit über Decisions; belegte Metadaten über Extractions.
- Feste API-Endpunkte und Modellkennung; keine Chat-Completions, keine erdachten Metadaten, explizite Nicht-Zuordnung und Prüfung bei API-Fehlern. Externe KI-Freigabe, bestehende Ablageregeln und Konfidenzgrenzen bleiben unverändert.

## 0.1.6 – 2026-11-27

- Eigene OCR-Einstellung für NVIDIA Nemotron OCR v2 (multilingual) mit separatem verschlüsseltem API-Key und ausdrücklicher Freigabe der Bildübertragung.
- PDF-Seiten werden bei Bedarf einzeln gerendert, Bilder direkt verarbeitet; eingebetteter Text bleibt erhalten. Kein Chat-Completions-Aufruf, kein OCR-PDF-Derivat.
- Die Oberfläche wird im App-Image aus dem Frontend-Quellcode gebaut.

## 0.1.5 – 2026-11-27

- „Erneut versuchen“ verarbeitet alle Dokumente im Zustand „Fehler“ neu, auch wenn ihr Job bereits regulär beendet ist

## 0.1.4 – 2026-11-27

- „Erneut versuchen“ setzt endgültig fehlgeschlagene Dokumente auf den passenden Schritt zurück und verarbeitet sie
  wirklich neu (vorher endeten die Jobs sofort wieder im Zustand „Fehler“)
- Erneute Analyse wiederholt die Textextraktion, wenn noch kein Text vorliegt

## 0.1.3 – 2026-11-27

- OCR: Tesseract-Daten für die Seitenausrichtung (osd) fehlten im Image, dadurch schlug die OCR für Scans fehl.
  Paket ergänzt; ohne osd wird die automatische Drehung übersprungen statt abzubrechen
- CI: Smoke-Test führt jetzt eine echte OCR im Image aus

## 0.1.2 – 2026-11-27

- Einstellungen: Browser-Autofill füllt die KI-Provider-Felder (Modell, API-Key) nicht mehr mit gespeicherten Zugangsdaten

## 0.1.1 – 2026-11-26

- KI-Provider: Apps im Supervisor-App-Netz (172.30.33.0/24, z. B. die Ollama-App) sind als lokale Provider erreichbar;
  gesperrt bleiben nur die Supervisor-Infrastruktur (172.30.32.0/24) und Cloud-Metadaten

## 0.1.0 – 2026-11-26 (Vorabversion)

- Erste installierbare Version als Home-Assistant-App (amd64, aarch64)
- Quellen: Gmail (lesend, History-API), Google-Drive-Eingangsordner, lokaler Eingang, Upload
- Pipeline mit Zustandsmaschine und Journal: Validierung, SHA-256-Duplikate, Textextraktion, lokale OCR,
  Regeln/KI, Ablage in Google Drive (Verschieben mit Erhalt der Datei-ID bzw. Upload), Verifikation, Bereinigung
- Beobachtungsmodus (Standard), Prüfmodus, automatischer Modus erst nach Testlauf
- Weboberfläche über Ingress mit Einrichtungsassistent
- Konsistenter Datenbank-Snapshot für Home-Assistant-Backups

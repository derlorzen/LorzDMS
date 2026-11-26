# Changelog

## 0.1.0 – 2026-11-26 (Vorabversion)

- Erste installierbare Version als Home-Assistant-App (amd64, aarch64)
- Quellen: Gmail (lesend, History-API), Google-Drive-Eingangsordner, lokaler Eingang, Upload
- Pipeline mit Zustandsmaschine und Journal: Validierung, SHA-256-Duplikate, Textextraktion, lokale OCR,
  Regeln/KI, Ablage in Google Drive (Verschieben mit Erhalt der Datei-ID bzw. Upload), Verifikation, Bereinigung
- Beobachtungsmodus (Standard), Prüfmodus, automatischer Modus erst nach Testlauf
- Weboberfläche über Ingress mit Einrichtungsassistent
- Konsistenter Datenbank-Snapshot für Home-Assistant-Backups

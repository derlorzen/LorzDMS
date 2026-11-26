# Drittkomponenten

| Komponente | Lizenz | Nutzung |
|---|---|---|
| OCRmyPDF | MPL-2.0 | unverändert, als Programm (pip) |
| Tesseract OCR + Sprachdaten deu/eng | Apache-2.0 | Alpine-Paket |
| Ghostscript | AGPL-3.0 | Alpine-Paket, separater Prozess (nur von OCRmyPDF für PDF/A aufgerufen) |
| pikepdf, qpdf | MPL-2.0, Apache-2.0 | Abhängigkeit von OCRmyPDF |
| pypdfium2 / PDFium | Apache-2.0 / BSD-3-Clause | Textextraktion, Seitenvorschau |
| FastAPI, Starlette, Uvicorn | MIT, BSD-3-Clause | Webserver |
| Pydantic | MIT | Validierung |
| httpx | BSD-3-Clause | HTTP-Client |
| cryptography | Apache-2.0 / BSD | Verschlüsselung |
| Pillow | MIT-CMU | Bildprüfung |
| python-multipart | Apache-2.0 | Uploads |
| React, React DOM | MIT | Oberfläche |
| Tailwind CSS | MIT | Oberfläche (Build-Zeit) |
| Vite, TypeScript | MIT, Apache-2.0 | Build-Zeit |
| Home Assistant base image, bashio, s6-overlay | Apache-2.0 / MIT / ISC | Container-Basis |
| reportlab (nur Tests) | BSD | synthetische Testdokumente |

Konzepte (kein Code übernommen): PaperSort (Apache-2.0), Paperless-ngx (GPL-3.0),
minimalmerlin/ai-document-sorter (MIT), RatnamOjha/AI-Drive-Organizer (MIT). DocuSort ist
source-available ohne Bearbeitungsrecht und wurde nur funktional betrachtet.

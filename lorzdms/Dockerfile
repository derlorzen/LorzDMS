# https://contributors.home-assistant.io/apps/guides/dockerfile/
ARG BUILD_FROM=ghcr.io/home-assistant/base:3.23
FROM node:22-alpine AS frontend
WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM ${BUILD_FROM}

# Systempakete: Python, Tesseract (Deutsch/Englisch), Ghostscript (PDF/A), Hilfsprogramme
RUN apk add --no-cache \
        python3 \
        py3-pip \
        tesseract-ocr \
        tesseract-ocr-data-deu \
        tesseract-ocr-data-eng \
        tesseract-ocr-data-osd \
        ghostscript \
        pngquant \
        unpaper \
        sqlite \
    && python3 -m venv /opt/venv

COPY app/requirements.txt /opt/lorzdms/requirements.txt
RUN /opt/venv/bin/pip install --no-cache-dir --only-binary=:all: -r /opt/lorzdms/requirements.txt \
    && /opt/venv/bin/ocrmypdf --version

# Anwendung und frisch aus dem Frontend-Quellcode gebaute Oberfläche
COPY app/lorzdms /opt/lorzdms/lorzdms
RUN rm -rf /opt/lorzdms/lorzdms/static
COPY --from=frontend /build/app/lorzdms/static /opt/lorzdms/lorzdms/static
COPY rootfs /

ENV PATH="/opt/venv/bin:${PATH}" \
    PYTHONPATH="/opt/lorzdms" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN chmod a+x /usr/bin/lorzdms-backup-pre \
    && python3 -m compileall -q /opt/lorzdms/lorzdms

LABEL \
    org.opencontainers.image.title="Home Assistant App: LorzDMS" \
    org.opencontainers.image.description="KI-gestütztes Dokumentenmanagement mit Google Drive" \
    org.opencontainers.image.source="https://github.com/derlorzen/LorzDMS" \
    org.opencontainers.image.licenses="Apache-2.0"

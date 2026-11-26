# https://contributors.home-assistant.io/apps/guides/dockerfile/
ARG BUILD_FROM=ghcr.io/home-assistant/base:3.23
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

# Anwendung (inkl. vorab gebauter Weboberfläche in lorzdms/static)
COPY app/lorzdms /opt/lorzdms/lorzdms
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

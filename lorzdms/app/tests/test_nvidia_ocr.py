import json

import httpx
import pytest
from PIL import Image

from lorzdms import appsettings, crypto
from lorzdms.google import http as ghttp
from lorzdms.pipeline import nvidia_ocr, text


def test_nvidia_multilingual_image(settings, tmp_path, monkeypatch):
    appsettings.set("allow_external_ocr", True)
    crypto.put_secret("ocr_api_key", "test-key")
    src = tmp_path / "scan.png"
    Image.new("RGB", (200, 300), "white").save(src)

    def handler(request):
        assert str(request.url) == nvidia_ocr.ENDPOINT
        assert request.method == "POST"
        assert request.headers["Authorization"] == "Bearer test-key"
        body = json.loads(request.content)
        assert body["input"][0]["url"].startswith("data:image/jpeg;base64,")
        assert body["merge_levels"] == ["paragraph"]
        assert "messages" not in body
        assert "language" not in body
        return httpx.Response(200, json={"data": [{"index": 0, "text_detections": [
            {"text_prediction": {"text": "Grüße – 日本語"}},
            {"text_prediction": {"text": "中文 Русский"}},
        ]}]})

    monkeypatch.setattr(ghttp, "_transport", httpx.MockTransport(handler))
    result = nvidia_ocr.extract(src, "image/png", timeout=10)
    assert result.text == "Grüße – 日本語\n中文 Русский"
    assert result.ocr_used and result.page_count == 1 and result.derivative is None


def test_nvidia_requires_consent(settings, tmp_path, monkeypatch):
    appsettings.set("allow_external_ocr", False)
    monkeypatch.setattr(httpx.Client, "post", lambda *a, **k: pytest.fail("No network without consent"))
    with pytest.raises(text.OcrFailed, match="nicht freigegeben"):
        nvidia_ocr.extract(tmp_path / "not-read.png", "image/png", timeout=10)


def test_nvidia_error_does_not_expose_key(settings, tmp_path, monkeypatch):
    appsettings.set("allow_external_ocr", True)
    crypto.put_secret("ocr_api_key", "test-key")
    src = tmp_path / "scan.png"
    Image.new("RGB", (20, 20)).save(src)
    monkeypatch.setattr(ghttp, "_transport", httpx.MockTransport(
        lambda request: httpx.Response(401, text="test-key")))
    with pytest.raises(text.OcrFailed, match="HTTP 401") as exc:
        nvidia_ocr.extract(src, "image/png", timeout=10)
    assert "test-key" not in str(exc.value)


def test_nvidia_pdf_pages(settings, tmp_path, monkeypatch):
    appsettings.set("allow_external_ocr", True)
    crypto.put_secret("ocr_api_key", "test-key")
    src = tmp_path / "scan.pdf"
    first = Image.new("RGB", (200, 300), "white")
    second = Image.new("RGB", (200, 300), "white")
    first.save(src, save_all=True, append_images=[second])
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"data": [{"index": 0, "text_detections": [
            {"text_prediction": {"text": f"Seite {len(calls)}"}},
        ]}]})

    monkeypatch.setattr(ghttp, "_transport", httpx.MockTransport(handler))
    result = nvidia_ocr.extract(src, "application/pdf", timeout=10)
    assert result.pages == ["Seite 1", "Seite 2"]
    assert result.page_count == 2 and len(calls) == 2

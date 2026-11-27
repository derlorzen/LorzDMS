import json

import httpx
import pytest

from lorzdms.ai import decider, providers
from lorzdms.google import http as ghttp

CFG = providers.ProviderConfig(decider.KIND, decider.BASE_URL, decider.MODEL, "test-key")
TEXT = "Rechnung\nMüller GmbH\nRechnungsnummer RE-42\nDatum 27.11.2026\nGesamt 1.234,56 EUR\nFällig 15.12.2026"
FOLDERS = [
    {"drive_id": "drive-a", "path": "Dokumente/Nebengewerbe/Rechnungen"},
    {"drive_id": "drive-b", "path": "Dokumente/Privat"},
]


def choose(spec, winner, probability=1.0):
    keys = list(spec["criteria"])
    return {"type": "choice", "choice": winner,
            "probabilities": {k: probability if k == winner else (1-probability)/(len(keys)-1) for k in keys}}


def fake_handler(calls, *, abstain=False, invalid=False, highly_sensitive=False):
    def handler(request):
        calls.append(request)
        assert request.headers["Authorization"] == "Bearer test-key"
        body = json.loads(request.content)
        assert body["model"] == decider.MODEL and body["state"] == TEXT
        assert "messages" not in body
        if request.url.path.endswith("/decisions"):
            assert "fields" not in body
            questions = body["questions"]
            assert questions["folder"]["criteria"]["folder_0"].startswith(FOLDERS[0]["path"])
            answers = {
                "document_type": choose(questions["document_type"], "invoice"),
                "confidentiality": choose(questions["confidentiality"], "highly_sensitive" if highly_sensitive else "sensitive"),
                "folder": choose(questions["folder"], "no_match" if abstain else "folder_0", .94),
                "topic": choose(questions["topic"], "it", .6),
            }
            if invalid:
                answers["folder"]["choice"] = "unapproved-folder"
        else:
            assert request.url.path.endswith("/extractions")
            assert "questions" not in body
            answers = {k: {"type": v["type"], "value": None} for k, v in body["fields"].items()}
            for key, value in {"sender": "Müller GmbH", "invoice_number": "RE-42", "document_date": "27.11.2026",
                               "amount": "1.234,56", "currency": "EUR", "due_date": "15.12.2026"}.items():
                start = TEXT.index(value)
                answers[key] = {"type": "text", "value": value, "span": [start, start+len(value)], "confidence": .99}
            # Hallucinated number must never be accepted even with high confidence.
            answers["contract_number"] = {"type": "text", "value": "invented", "span": [0, 9], "confidence": 1}
        return httpx.Response(200, json={"answers": answers, "usage": {"input_tokens": 100, "output_tokens": 0}})
    return handler


def test_native_decider(settings, monkeypatch):
    calls = []
    monkeypatch.setattr(ghttp, "_transport", httpx.MockTransport(fake_handler(calls)))
    call = providers.analyze(CFG, TEXT, FOLDERS, {}, allow_external=True)
    assert [r.url.path for r in calls] == ["/api/alpha/decisions", "/api/alpha/extractions"]
    assert call.result.suggested_folder_id == "drive-a"
    assert call.result.confidence == .94
    assert call.result.alternative_folder_ids == ["drive-b"]
    assert call.result.document_type == "Rechnung"
    assert call.result.sender == "Müller GmbH"
    assert call.result.invoice_number == "RE-42"
    assert call.result.document_date == "2026-11-27"
    assert call.result.due_date == "2026-12-15"
    assert call.result.amount == 1234.56
    assert call.result.currency == "EUR"
    assert call.result.contract_number is None
    assert call.result.tags == ["IT & Telefon"]
    assert call.input_tokens == 200 and call.output_tokens == 0


def test_decider_abstains_and_marks_sensitive(settings, monkeypatch):
    monkeypatch.setattr(ghttp, "_transport", httpx.MockTransport(fake_handler([], abstain=True, highly_sensitive=True)))
    result = providers.analyze(CFG, TEXT, FOLDERS, {}, allow_external=True).result
    assert result.suggested_folder_id is None and result.confidence == 0
    assert result.confidentiality == "highly_sensitive"


def test_decider_rejects_unapproved_choice(settings, monkeypatch):
    monkeypatch.setattr(ghttp, "_transport", httpx.MockTransport(fake_handler([], invalid=True)))
    with pytest.raises(providers.ProviderError, match="ungültige"):
        providers.analyze(CFG, TEXT, FOLDERS, {}, allow_external=True)


def test_decider_requires_external_consent(settings, monkeypatch):
    monkeypatch.setattr(ghttp, "_transport", httpx.MockTransport(lambda r: pytest.fail("No network without consent")))
    with pytest.raises(providers.ExternalNotAllowed):
        providers.analyze(CFG, TEXT, FOLDERS, {}, allow_external=False)


def test_decider_http_failure(settings, monkeypatch):
    monkeypatch.setattr(ghttp, "_transport", httpx.MockTransport(lambda r: httpx.Response(429, text="test-key")))
    with pytest.raises(providers.ProviderError, match="HTTP 429") as exc:
        providers.analyze(CFG, TEXT, FOLDERS, {}, allow_external=True)
    assert "test-key" not in str(exc.value)


def test_decider_rejects_wrong_endpoint(settings, monkeypatch):
    cfg = providers.ProviderConfig(decider.KIND, "https://example.org", decider.MODEL, "test-key")
    monkeypatch.setattr(ghttp, "_transport", httpx.MockTransport(lambda r: pytest.fail("Do not send credentials")))
    with pytest.raises(providers.ProviderError, match="nativen"):
        providers.analyze(cfg, TEXT, FOLDERS, {}, allow_external=True)

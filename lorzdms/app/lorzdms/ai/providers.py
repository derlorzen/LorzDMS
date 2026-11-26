"""KI-Provider. Alle liefern ein validiertes :class:`AnalysisResult`.

- ``ollama``: lokaler/selbst gehosteter Ollama-Server (``/api/chat``, JSON-Schema-Format)
- ``openai_compatible``: OpenAI, OpenRouter, Mistral, Azure-OpenAI-kompatible Gateways,
  LM Studio, vLLM, LocalAI (``/v1/chat/completions``)
- ``anthropic``: Anthropic Messages API

Externe Provider dürfen nur genutzt werden, wenn ``allow_external_ai`` aktiviert ist.
"""

from __future__ import annotations

import ipaddress
import json
import re
import socket
import time
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx
from pydantic import ValidationError

from ..google import http as ghttp
from .prompt import build_messages
from .schema import AnalysisResult, json_schema

BLOCKED_NETS = [
    ipaddress.ip_network("169.254.0.0/16"),   # Cloud-Metadaten
    # Supervisor-Infrastruktur (Core .1, Supervisor .2, DNS, Audio, CLI, Observer …).
    # Das App-Netz 172.30.33.0/24 bleibt erlaubt, damit z. B. die Ollama-App erreichbar ist.
    ipaddress.ip_network("172.30.32.0/24"),
    ipaddress.ip_network("0.0.0.0/8"),
]


class ProviderError(RuntimeError):
    pass


class ExternalNotAllowed(ProviderError):
    pass


@dataclass
class ProviderConfig:
    kind: str
    base_url: str
    model: str
    api_key: str | None = None
    timeout: float = 120.0


@dataclass
class AiCall:
    result: AnalysisResult
    input_tokens: int | None
    output_tokens: int | None
    seconds: float
    provider: str
    model: str


def _resolve(host: str) -> list[ipaddress._BaseAddress]:
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return []
    return [ipaddress.ip_address(i[4][0]) for i in infos]


def check_url(url: str) -> bool:
    """SSRF-Schutz. Rückgabe: True, wenn das Ziel lokal/privat ist (kein externer Dienst)."""
    p = urlparse(url)
    if p.scheme not in ("http", "https") or not p.hostname:
        raise ProviderError("Ungültige Provider-URL")
    addrs = _resolve(p.hostname)
    if not addrs:
        raise ProviderError(f"Host {p.hostname} nicht auflösbar")
    for a in addrs:
        if any(a in n for n in BLOCKED_NETS):
            raise ProviderError("Ziel-Adresse ist gesperrt (Metadaten-/Supervisor-Netz)")
    private = all(a.is_private or a.is_loopback for a in addrs)
    if not private and p.scheme != "https":
        raise ProviderError("Externe Provider nur über HTTPS")
    return private


def is_external(cfg: ProviderConfig) -> bool:
    if cfg.kind == "anthropic":
        return True
    return not check_url(cfg.base_url)


def _extract_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("Antwort enthält kein JSON-Objekt")
    return json.loads(text[start : end + 1])


def _post(url: str, headers: dict, body: dict, timeout: float) -> dict:
    with httpx.Client(transport=ghttp._transport, timeout=timeout) as c:
        resp = c.post(url, headers=headers, json=body)
    if resp.status_code >= 400:
        raise ProviderError(f"Provider-Fehler HTTP {resp.status_code}")
    return resp.json()


def analyze(cfg: ProviderConfig, text: str, folders: list[dict], hints: dict, *, allow_external: bool) -> AiCall:
    if is_external(cfg) and not allow_external:
        raise ExternalNotAllowed("Externer KI-Provider ist nicht freigegeben (allow_external_ai)")
    system, user = build_messages(text, folders, hints)
    schema = json_schema()
    last_error: Exception | None = None
    for attempt in range(2):
        started = time.monotonic()
        content, tin, tout = _call(cfg, system, user, schema)
        elapsed = time.monotonic() - started
        try:
            result = AnalysisResult.model_validate(_extract_json(content))
        except (ValueError, ValidationError) as exc:
            last_error = exc
            user += "\n\nDie letzte Antwort war kein gültiges JSON nach Schema. Antworte nur mit dem JSON-Objekt."
            continue
        valid_ids = {f["drive_id"] for f in folders}
        if result.suggested_folder_id and result.suggested_folder_id not in valid_ids:
            result.uncertainties.append("Vorgeschlagener Ordner existiert nicht und wurde verworfen")
            result.suggested_folder_id = None
        result.alternative_folder_ids = [f for f in result.alternative_folder_ids if f in valid_ids]
        return AiCall(result, tin, tout, elapsed, cfg.kind, cfg.model)
    raise ProviderError(f"Ungültige KI-Antwort: {type(last_error).__name__}")


def _call(cfg: ProviderConfig, system: str, user: str, schema: dict) -> tuple[str, int | None, int | None]:
    base = cfg.base_url.rstrip("/")
    if cfg.kind == "ollama":
        data = _post(
            f"{base}/api/chat",
            {},
            {"model": cfg.model, "stream": False, "format": schema, "options": {"temperature": 0},
             "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]},
            cfg.timeout,
        )
        return data.get("message", {}).get("content", ""), data.get("prompt_eval_count"), data.get("eval_count")
    if cfg.kind == "openai_compatible":
        headers = {"Authorization": f"Bearer {cfg.api_key}"} if cfg.api_key else {}
        data = _post(
            f"{base}/chat/completions",
            headers,
            {"model": cfg.model, "temperature": 0,
             "response_format": {"type": "json_schema", "json_schema": {"name": "analysis", "schema": schema}},
             "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]},
            cfg.timeout,
        )
        usage = data.get("usage") or {}
        return data["choices"][0]["message"]["content"] or "", usage.get("prompt_tokens"), usage.get("completion_tokens")
    if cfg.kind == "anthropic":
        if not cfg.api_key:
            raise ProviderError("API-Key fehlt")
        data = _post(
            f"{base}/v1/messages",
            {"x-api-key": cfg.api_key, "anthropic-version": "2023-06-01"},
            {"model": cfg.model, "max_tokens": 2000, "temperature": 0, "system": system + "\nJSON-Schema:\n" + json.dumps(schema),
             "messages": [{"role": "user", "content": user}]},
            cfg.timeout,
        )
        text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
        usage = data.get("usage") or {}
        return text, usage.get("input_tokens"), usage.get("output_tokens")
    raise ProviderError(f"Unbekannter Provider-Typ {cfg.kind}")

"""Gemeinsamer HTTP-Client für Google-APIs mit Retry bei transienten Fehlern.

Der Transport ist austauschbar (Tests verwenden ``httpx.MockTransport``).
TLS-Prüfung bleibt immer aktiv.
"""

from __future__ import annotations

import random
import time
from typing import Callable

import httpx

TRANSIENT = {408, 429, 500, 502, 503, 504}
_transport: httpx.BaseTransport | None = None
_sleep: Callable[[float], None] = time.sleep


def set_transport(transport: httpx.BaseTransport | None) -> None:
    global _transport
    _transport = transport


def set_sleep(fn: Callable[[float], None]) -> None:
    global _sleep
    _sleep = fn


def client(timeout: float = 60.0) -> httpx.Client:
    return httpx.Client(transport=_transport, timeout=timeout, follow_redirects=False)


class GoogleApiError(RuntimeError):
    def __init__(self, status: int, message: str, reason: str = ""):
        super().__init__(f"HTTP {status}: {message}")
        self.status = status
        self.reason = reason


class AuthExpired(GoogleApiError):
    """Refresh-Token ungültig/widerrufen: Reautorisierung nötig."""


def _error(resp: httpx.Response) -> GoogleApiError:
    try:
        body = resp.json()
        err = body.get("error")
        if isinstance(err, dict):
            msg = err.get("message", "")
            reason = (err.get("errors") or [{}])[0].get("reason", "") or err.get("status", "")
        else:
            msg = body.get("error_description") or str(err)
            reason = str(err)
    except ValueError:
        msg, reason = resp.text[:300], ""
    if resp.status_code in (400, 401) and reason in ("invalid_grant", "unauthorized_client"):
        return AuthExpired(resp.status_code, msg, reason)
    return GoogleApiError(resp.status_code, msg, reason)


def request(
    method: str,
    url: str,
    *,
    retries: int = 5,
    rate_limit_reasons: tuple[str, ...] = ("rateLimitExceeded", "userRateLimitExceeded"),
    **kwargs,
) -> httpx.Response:
    attempt = 0
    while True:
        attempt += 1
        try:
            with client() as c:
                resp = c.request(method, url, **kwargs)
        except (httpx.TransportError,) as exc:
            if attempt > retries:
                raise GoogleApiError(0, f"Verbindungsfehler: {type(exc).__name__}") from exc
            _sleep(min(60, 2 ** attempt) * random.uniform(0.5, 1.0))
            continue
        if resp.status_code < 400:
            return resp
        err = _error(resp)
        retry = resp.status_code in TRANSIENT or (resp.status_code == 403 and err.reason in rate_limit_reasons)
        if retry and attempt <= retries:
            _sleep(min(60, 2 ** attempt) * random.uniform(0.5, 1.0))
            continue
        raise err

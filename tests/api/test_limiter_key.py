"""Rate-limit key must resolve the real client IP behind a trusted proxy, and
must NOT trust the forwarded header unless the operator opted in."""
from __future__ import annotations

from starlette.requests import Request

from repi.api.limiter import _client_key
from repi.core.config import settings


def _req(headers: dict, client_host: str = "10.0.0.1") -> Request:
    scope = {
        "type": "http",
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
        "client": (client_host, 12345),
    }
    return Request(scope)


def test_defaults_to_peer_when_header_unset(monkeypatch):
    monkeypatch.setattr(settings, "TRUSTED_CLIENT_IP_HEADER", "")
    # Even if a client spoofs XFF, we ignore it and use the socket peer.
    assert _client_key(_req({"x-forwarded-for": "1.2.3.4"}, "10.0.0.1")) == "10.0.0.1"


def test_uses_trusted_header_first_hop(monkeypatch):
    monkeypatch.setattr(settings, "TRUSTED_CLIENT_IP_HEADER", "fly-client-ip")
    assert _client_key(_req({"fly-client-ip": "203.0.113.9"})) == "203.0.113.9"


def test_trusted_header_takes_first_of_list(monkeypatch):
    monkeypatch.setattr(settings, "TRUSTED_CLIENT_IP_HEADER", "x-forwarded-for")
    assert _client_key(_req({"x-forwarded-for": "203.0.113.9, 10.0.0.1"})) == "203.0.113.9"


def test_falls_back_when_trusted_header_absent(monkeypatch):
    monkeypatch.setattr(settings, "TRUSTED_CLIENT_IP_HEADER", "fly-client-ip")
    assert _client_key(_req({}, "10.0.0.7")) == "10.0.0.7"

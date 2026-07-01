from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request

from repi.core.config import settings


def _client_key(request: Request) -> str:
    """Rate-limit key = the real client IP.

    Behind a trusted edge proxy, `request.client.host` is the proxy's IP, which
    collapses every user into one bucket. When TRUSTED_CLIENT_IP_HEADER is set
    we key on that header's first hop instead. It must only be set for a
    platform that pins/overwrites the header (else it is client-spoofable).
    """
    header = settings.TRUSTED_CLIENT_IP_HEADER
    if header:
        value = request.headers.get(header)
        if value:
            return value.split(",")[0].strip()
    return get_remote_address(request)


limiter = Limiter(key_func=_client_key)

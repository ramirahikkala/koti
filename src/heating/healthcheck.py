"""Optional healthchecks.io-style dead-man ping."""

from __future__ import annotations

import httpx
import structlog

log = structlog.get_logger(__name__)


def ping(url: str | None, *, success: bool) -> None:
    if not url:
        return
    target = url if success else f"{url.rstrip('/')}/fail"
    try:
        httpx.get(target, timeout=10)
    except httpx.HTTPError as exc:
        log.warning("healthcheck.ping_failed", error=str(exc))

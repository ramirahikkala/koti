"""Home Assistant REST API client (httpx).

Generalised from v1 ``src/ha_client.py`` - no entity-specific wrappers; callers pass entity
ids from zone config.
"""

from __future__ import annotations

import time
from typing import Any

import httpx
import structlog

log = structlog.get_logger(__name__)

_UNAVAILABLE = {"unavailable", "unknown", "none", ""}


class HAClient:
    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        timeout: float = 10.0,
        retries: int = 3,
        client: httpx.Client | None = None,
    ) -> None:
        self._retries = retries
        self._client = client or httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            timeout=timeout,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> HAClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ----------------------------------------------------------------- internals

    def _get(self, path: str) -> httpx.Response | None:
        delay = 1.0
        for attempt in range(1, self._retries + 1):
            try:
                resp = self._client.get(path)
                resp.raise_for_status()
                return resp
            except httpx.HTTPError as exc:
                log.warning("ha.get_failed", path=path, attempt=attempt, error=str(exc))
                if attempt < self._retries:
                    time.sleep(delay)
                    delay *= 2
        return None

    # ------------------------------------------------------------------- states

    def get_state(self, entity_id: str) -> str | None:
        resp = self._get(f"/api/states/{entity_id}")
        if resp is None:
            return None
        state = str(resp.json().get("state", "")).strip()
        return None if state.lower() in _UNAVAILABLE else state

    def get_state_float(self, entity_id: str) -> float | None:
        state = self.get_state(entity_id)
        if state is None:
            return None
        try:
            return float(state)
        except ValueError:
            log.warning("ha.state_not_numeric", entity_id=entity_id, state=state)
            return None

    # ----------------------------------------------------------------- services

    def call_service(self, domain: str, service: str, data: dict[str, Any]) -> bool:
        try:
            resp = self._client.post(f"/api/services/{domain}/{service}", json=data)
            resp.raise_for_status()
            return True
        except httpx.HTTPError as exc:
            log.error("ha.service_failed", domain=domain, service=service, error=str(exc))
            return False

    def set_switch(self, entity_id: str, on: bool, *, verify: bool = True) -> bool:
        """Turn a switch on/off and (optionally) confirm the resulting state."""
        service = "turn_on" if on else "turn_off"
        if not self.call_service("switch", service, {"entity_id": entity_id}):
            return False
        if not verify:
            return True

        expected = "on" if on else "off"
        for attempt in range(10):
            time.sleep(0.5 if attempt == 0 else 1.0)
            state = self.get_state(entity_id)
            if state == expected:
                log.info("ha.switch_set", entity_id=entity_id, state=expected)
                return True
        log.warning("ha.switch_unconfirmed", entity_id=entity_id, expected=expected)
        return True

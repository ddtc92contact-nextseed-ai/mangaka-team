"""Client HTTP ComfyUI : /prompt, /history, /view, /queue, /system_stats.

Le suivi de progression par websocket arrivera avec la file de génération (jalon 2).
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from typing import Any

import httpx

from .base import (
    ComfyStatus,
    ComfyUIError,
    ComfyUITimeoutError,
    ComfyUIUnavailableError,
    ComfyUIWorkflowError,
    ImageRef,
    images_from_history,
)


class HttpComfyUIClient:
    name = "http"

    def __init__(
        self,
        base_url: str,
        *,
        timeout_s: float = 5.0,
        client_id: str | None = None,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.client_id = client_id or uuid.uuid4().hex
        self._sleep = sleep
        self._clock = clock
        self._client = httpx.Client(base_url=self.base_url, timeout=timeout_s, transport=transport)

    # --- bas niveau -------------------------------------------------------
    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            return self._client.request(method, path, **kwargs)
        except httpx.TimeoutException as exc:
            raise ComfyUIUnavailableError(f"ComfyUI ne répond pas ({self.base_url})") from exc
        except httpx.HTTPError as exc:
            raise ComfyUIUnavailableError(f"ComfyUI injoignable ({self.base_url})") from exc

    def _json(self, resp: httpx.Response) -> Any:
        try:
            return resp.json()
        except ValueError as exc:
            raise ComfyUIError(f"réponse ComfyUI illisible (HTTP {resp.status_code})") from exc

    # --- API --------------------------------------------------------------
    def health(self) -> ComfyStatus:
        try:
            stats = self._request("GET", "/system_stats")
            if stats.status_code != 200:
                raise ComfyUIError(f"HTTP {stats.status_code} sur /system_stats")
            queue = self._request("GET", "/queue")
            q = self._json(queue) if queue.status_code == 200 else {}
        except ComfyUIError as exc:
            return ComfyStatus(online=False, provider=self.name, url=self.base_url, detail=str(exc))
        return ComfyStatus(
            online=True,
            provider=self.name,
            url=self.base_url,
            queue_running=len(q.get("queue_running", []) or []),
            queue_pending=len(q.get("queue_pending", []) or []),
        )

    def queue_prompt(self, workflow: dict[str, Any]) -> str:
        resp = self._request("POST", "/prompt", json={"prompt": workflow, "client_id": self.client_id})
        data = self._json(resp)
        if resp.status_code != 200:
            err = data.get("error") if isinstance(data, dict) else None
            message = err.get("message") if isinstance(err, dict) else None
            node_errors = data.get("node_errors") if isinstance(data, dict) else None
            raise ComfyUIWorkflowError(
                f"workflow refusé par ComfyUI : {message or f'HTTP {resp.status_code}'}", node_errors
            )
        prompt_id = data.get("prompt_id") if isinstance(data, dict) else None
        if not isinstance(prompt_id, str):
            raise ComfyUIError("ComfyUI n'a pas renvoyé de prompt_id")
        return prompt_id

    def get_history(self, prompt_id: str) -> dict[str, Any] | None:
        resp = self._request("GET", f"/history/{prompt_id}")
        if resp.status_code != 200:
            raise ComfyUIError(f"HTTP {resp.status_code} sur /history")
        data = self._json(resp)
        entry = data.get(prompt_id) if isinstance(data, dict) else None
        return entry if isinstance(entry, dict) else None

    def wait_for_images(
        self, prompt_id: str, output_node: str, *, timeout_s: float = 600, poll_s: float = 1.0
    ) -> list[ImageRef]:
        deadline = self._clock() + timeout_s
        while True:
            entry = self.get_history(prompt_id)
            if entry is not None:
                images = images_from_history(entry, output_node)
                if images:
                    return images
            if self._clock() >= deadline:
                raise ComfyUITimeoutError(f"génération {prompt_id} non terminée après {timeout_s:.0f} s")
            self._sleep(poll_s)

    def fetch_image(self, ref: ImageRef) -> bytes:
        resp = self._request(
            "GET", "/view", params={"filename": ref.filename, "subfolder": ref.subfolder, "type": ref.type}
        )
        if resp.status_code != 200:
            raise ComfyUIError(f"image {ref.filename} introuvable (HTTP {resp.status_code})")
        return resp.content

    def close(self) -> None:
        self._client.close()

"""Client HTTP ComfyUI : /prompt, /history, /view, /queue, /system_stats, /upload/image, /interrupt.

La progression d'une génération est suivie par le websocket `/ws?clientId=` ; s'il est
indisponible, on se contente de sonder `/history` (sans progression intermédiaire).
"""

from __future__ import annotations

import contextlib
import json
import logging
import mimetypes
import time
import uuid
from collections.abc import Callable
from typing import Any, Protocol
from urllib.parse import quote, urlsplit, urlunsplit

import httpx

from .base import (
    ComfyStatus,
    ComfyUIError,
    ComfyUIInterruptedError,
    ComfyUITimeoutError,
    ComfyUIUnavailableError,
    ComfyUIWorkflowError,
    ImageRef,
    ProgressFn,
    StopFn,
    check_prompt_nodes,
    describe_prompt_error,
    images_from_history,
)

log = logging.getLogger("mangaka_engine")

OBJECT_INFO_TIMEOUT_S = 60.0


class WebSocketLike(Protocol):
    def recv(self, timeout: float | None = None) -> str | bytes: ...

    def close(self) -> None: ...


WsConnect = Callable[[str], WebSocketLike]


def _default_ws_connect(timeout_s: float) -> WsConnect:
    def connect(url: str) -> WebSocketLike:
        from websockets.sync.client import connect as ws_connect

        return ws_connect(url, open_timeout=timeout_s, max_size=None)

    return connect


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
        ws_connect: WsConnect | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.address = urlsplit(self.base_url).netloc or self.base_url
        self.client_id = client_id or uuid.uuid4().hex
        self._sleep = sleep
        self._clock = clock
        # Sans transport réel (tests), pas de websocket : sondage de /history seulement.
        self._ws_connect = (
            ws_connect if ws_connect is not None else (_default_ws_connect(timeout_s) if transport is None else None)
        )
        self._client = httpx.Client(base_url=self.base_url, timeout=timeout_s, transport=transport)

    # --- bas niveau -------------------------------------------------------
    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            return self._client.request(method, path, **kwargs)
        except httpx.TimeoutException as exc:
            raise ComfyUIUnavailableError(f"ComfyUI ne répond pas ({self.address})") from exc
        except httpx.HTTPError as exc:
            raise ComfyUIUnavailableError(f"ComfyUI hors ligne ({self.address})") from exc

    def _json(self, resp: httpx.Response) -> Any:
        try:
            return resp.json()
        except ValueError as exc:
            raise ComfyUIError(f"réponse ComfyUI illisible (HTTP {resp.status_code})") from exc

    @property
    def ws_url(self) -> str:
        parts = urlsplit(self.base_url)
        scheme = "wss" if parts.scheme == "https" else "ws"
        return urlunsplit((scheme, parts.netloc, f"{parts.path}/ws", f"clientId={self.client_id}", ""))

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

    def _get_dict(self, path: str, timeout_s: float | None = None) -> dict[str, Any]:
        kwargs: dict[str, Any] = {"timeout": timeout_s} if timeout_s is not None else {}
        resp = self._request("GET", path, **kwargs)
        if resp.status_code != 200:
            raise ComfyUIError(f"HTTP {resp.status_code} sur {path}")
        data = self._json(resp)
        if not isinstance(data, dict):
            raise ComfyUIError(f"réponse ComfyUI inattendue sur {path}")
        return data

    def system_stats(self) -> dict[str, Any]:
        return self._get_dict("/system_stats")

    def object_info(self) -> dict[str, Any]:
        # Plusieurs Mo (toutes les classes de nœuds et leurs listes de fichiers) : délai plus large.
        return self._get_dict("/object_info", timeout_s=OBJECT_INFO_TIMEOUT_S)

    def node_info(self, class_type: str) -> dict[str, Any]:
        # Une seule classe (ex. le chargeur de LoRA) : quelques Ko, délai normal.
        return self._get_dict(f"/object_info/{quote(class_type, safe='')}")

    def queue_prompt(self, workflow: dict[str, Any]) -> str:
        check_prompt_nodes(workflow)
        resp = self._request("POST", "/prompt", json={"prompt": workflow, "client_id": self.client_id})
        data = self._json(resp)
        if resp.status_code != 200:
            node_errors = data.get("node_errors") if isinstance(data, dict) else None
            raise ComfyUIWorkflowError(
                f"workflow refusé par ComfyUI : {describe_prompt_error(data, resp.status_code)}", node_errors
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
        self,
        prompt_id: str,
        output_node: str,
        *,
        timeout_s: float = 600,
        poll_s: float = 1.0,
        on_progress: ProgressFn | None = None,
        should_stop: StopFn | None = None,
    ) -> list[ImageRef]:
        deadline = self._clock() + timeout_s
        ws = self._open_ws() if on_progress is not None else None
        try:
            while True:
                if should_stop is not None and should_stop():
                    raise ComfyUIInterruptedError("génération annulée")
                entry = self.get_history(prompt_id)
                if entry is not None:
                    images = images_from_history(entry, output_node)
                    if images:
                        return images
                if self._clock() >= deadline:
                    raise ComfyUITimeoutError(f"génération {prompt_id} non terminée après {timeout_s:.0f} s")
                if ws is not None and on_progress is not None:
                    if not self._pump_ws(ws, prompt_id, on_progress, poll_s):
                        self._close_ws(ws)
                        ws = None
                else:
                    self._sleep(poll_s)
        finally:
            if ws is not None:
                self._close_ws(ws)

    # --- websocket de progression ------------------------------------------
    def _open_ws(self) -> WebSocketLike | None:
        if self._ws_connect is None:
            return None
        try:
            return self._ws_connect(self.ws_url)
        except Exception as exc:  # noqa: BLE001 — repli sur le sondage de /history
            log.info("websocket ComfyUI indisponible (%s) : progression par sondage", exc)
            return None

    @staticmethod
    def _close_ws(ws: WebSocketLike) -> None:
        with contextlib.suppress(Exception):
            ws.close()

    def _pump_ws(self, ws: WebSocketLike, prompt_id: str, on_progress: ProgressFn, wait_s: float) -> bool:
        """Lit les messages pendant au plus `wait_s` ; False si le websocket est inutilisable."""
        end = self._clock() + wait_s
        while True:
            remaining = end - self._clock()
            if remaining <= 0:
                return True
            try:
                raw = ws.recv(timeout=remaining)
            except TimeoutError:
                return True
            except Exception as exc:  # noqa: BLE001 — connexion fermée : repli sur le sondage
                log.info("websocket ComfyUI fermé (%s) : progression par sondage", exc)
                return False
            if isinstance(raw, bytes):
                continue  # aperçus binaires
            try:
                msg = json.loads(raw)
            except ValueError:
                continue
            if not isinstance(msg, dict):
                continue
            kind, data = msg.get("type"), msg.get("data") or {}
            if not isinstance(data, dict) or data.get("prompt_id") not in (None, prompt_id):
                continue
            if kind == "progress":
                value, maximum = data.get("value"), data.get("max")
                if isinstance(value, int) and isinstance(maximum, int) and maximum > 0:
                    on_progress(value, maximum)
            elif kind in ("executing", "execution_success") and data.get("node") is None:
                return True  # terminé : /history fait foi
            elif kind in ("execution_error", "execution_interrupted"):
                return True

    def fetch_image(self, ref: ImageRef) -> bytes:
        resp = self._request(
            "GET", "/view", params={"filename": ref.filename, "subfolder": ref.subfolder, "type": ref.type}
        )
        if resp.status_code != 200:
            raise ComfyUIError(f"image {ref.filename} introuvable (HTTP {resp.status_code})")
        return resp.content

    def upload_image(self, data: bytes, filename: str, *, subfolder: str = "mangaka") -> str:
        mime = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        resp = self._request(
            "POST",
            "/upload/image",
            files={"image": (filename, data, mime)},
            data={"subfolder": subfolder, "type": "input", "overwrite": "true"},
        )
        if resp.status_code != 200:
            raise ComfyUIError(f"envoi de l'image de référence {filename} refusé par ComfyUI (HTTP {resp.status_code})")
        body = self._json(resp)
        name = body.get("name") if isinstance(body, dict) else None
        if not isinstance(name, str) or not name:
            raise ComfyUIError("ComfyUI n'a pas renvoyé le nom de l'image envoyée")
        sub = body.get("subfolder") or ""
        return f"{sub}/{name}" if sub else name

    def interrupt(self, prompt_id: str | None = None) -> None:
        payload = {"prompt_id": prompt_id} if prompt_id else {}
        resp = self._request("POST", "/interrupt", json=payload)
        if resp.status_code != 200:
            raise ComfyUIError(f"interruption refusée par ComfyUI (HTTP {resp.status_code})")

    def close(self) -> None:
        self._client.close()

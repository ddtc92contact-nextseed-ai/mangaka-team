"""Client DeepSeek (API compatible OpenAI : POST {base_url}/chat/completions, GET {base_url}/models).

Modèles qui raisonnent (deepseek-reasoner) : la température n'est pas envoyée (refusée ou ignorée), seul
`content` est lu (`reasoning_content` est ignoré), et si le mode JSON est refusé (HTTP 400), la requête est
refaite une fois sans `response_format`, la consigne JSON passant par le prompt ; la validation et les nouveaux
essais des agents s'appliquent ensuite comme d'habitude.
"""

from __future__ import annotations

import re
import threading
import time
from collections.abc import Callable
from typing import Any

import httpx

from .base import (
    ChatMessage,
    LLMAuthError,
    LLMBadRequestError,
    LLMConfigError,
    LLMError,
    LLMRateLimitError,
    LLMResponseError,
    LLMResult,
    LLMTimeoutError,
    LLMUnavailableError,
)


class DeepSeekProvider:
    name = "deepseek"

    def __init__(
        self,
        *,
        api_key: str | None,
        base_url: str,
        model: str,
        timeout_s: float = 60,
        temperature: float = 0.7,
        reasoning: bool | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not api_key:
            raise LLMConfigError("DEEPSEEK_API_KEY manquante : renseigne-la dans .env ou utilise LLM_PROVIDER=mock")
        self.model = model
        self.temperature = temperature
        # None : deviné d'après le nom (modèle tapé à la main, absent de providers.yaml).
        self.reasoning = is_reasoning_model(model) if reasoning is None else reasoning
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=httpx.Timeout(timeout_s, connect=min(timeout_s, 10)),
            transport=transport,
        )

    def complete(
        self,
        messages: list[ChatMessage],
        *,
        json_mode: bool = False,
        temperature: float | None = None,
    ) -> LLMResult:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "stream": False,
        }
        if not self.reasoning:
            payload["temperature"] = self.temperature if temperature is None else temperature
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        resp = self._post(payload)
        if resp.status_code == 400 and json_mode and _JSON_REFUSED.search(_api_message(resp)):
            # Mode JSON refusé par ce modèle : la consigne passe par le prompt.
            payload.pop("response_format")
            payload["messages"] = [*payload["messages"], {"role": "system", "content": JSON_INSTRUCTION}]
            resp = self._post(payload)
        if resp.status_code >= 400:
            raise _map_status(resp, self.model)

        try:
            data = resp.json()
            message = data["choices"][0]["message"]
            text = message["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise LLMResponseError("réponse DeepSeek illisible") from exc
        if not isinstance(text, str) or (not text.strip() and message.get("reasoning_content")):
            raise LLMResponseError("réponse DeepSeek sans contenu texte (seulement le raisonnement)")
        if json_mode and "response_format" not in payload:
            text = _unfence(text)
        usage = {k: v for k, v in (data.get("usage") or {}).items() if isinstance(v, int)}
        return LLMResult(text=text, model=data.get("model", self.model), usage=usage)

    def _post(self, payload: dict[str, Any]) -> httpx.Response:
        try:
            return self._client.post("/chat/completions", json=payload)
        except httpx.TimeoutException as exc:
            raise LLMTimeoutError("DeepSeek n'a pas répondu à temps (timeout)") from exc
        except httpx.HTTPError as exc:
            raise LLMUnavailableError(f"DeepSeek injoignable : {exc.__class__.__name__}") from exc

    def close(self) -> None:
        self._client.close()


# 400 « mode JSON refusé » (réessai sans response_format) et « modèle inconnu » (nom à vérifier).
_JSON_REFUSED = re.compile(r"response_format|json", re.IGNORECASE)
_MODEL_NOT_FOUND = re.compile(r"model.*(not.*(exist|found)|unknown|invalid)|(unknown|invalid).*model", re.IGNORECASE)


def _api_message(resp: httpx.Response) -> str:
    try:
        err = resp.json().get("error")
        if isinstance(err, dict) and isinstance(err.get("message"), str):
            return err["message"]
    except ValueError:
        pass
    return ""


def _map_status(resp: httpx.Response, model: str | None = None) -> LLMError:
    status = resp.status_code
    detail = _api_message(resp)
    suffix = f" ({detail})" if detail else ""
    if model and status in (400, 404, 422) and _MODEL_NOT_FOUND.search(detail):
        suffix += f" — modèle « {model} » : vérifie son nom dans L'équipe"
    if status in (401, 403):
        return LLMAuthError(f"clé DeepSeek refusée (HTTP {status}){suffix}")
    if status == 402:
        return LLMAuthError(f"solde DeepSeek insuffisant (HTTP 402){suffix}")
    if status == 429:
        return LLMRateLimitError(f"trop de requêtes DeepSeek, réessaie plus tard (HTTP 429){suffix}")
    if status in (400, 404, 422):
        return LLMBadRequestError(f"requête refusée par DeepSeek (HTTP {status}){suffix}")
    if status >= 500:
        return LLMUnavailableError(f"DeepSeek indisponible (HTTP {status}){suffix}")
    return LLMError(f"erreur DeepSeek inattendue (HTTP {status}){suffix}")


JSON_INSTRUCTION = (
    "Réponds uniquement par un objet JSON valide, sans texte autour ni bloc de code : le mode JSON n'est pas "
    "disponible pour ce modèle."
)
_FENCE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL)


def _unfence(text: str) -> str:
    m = _FENCE.match(text)
    return m.group(1) if m else text


def is_reasoning_model(model: str) -> bool:
    """Modèle qui raisonne d'après son nom (deepseek-reasoner, *-r1…)."""
    name = model.strip().lower()
    return "reasoner" in name or bool(re.search(r"(^|[-_])r1($|[-_])", name))


# --- liste des modèles ---------------------------------------------------------------------------------
def fetch_models(
    *, api_key: str, base_url: str, timeout_s: float = 10, transport: httpx.BaseTransport | None = None
) -> list[str]:
    """Identifiants renvoyés par GET {base_url}/models ; `LLMError` lisible (sans la clé) sinon."""
    try:
        with httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=httpx.Timeout(timeout_s, connect=min(timeout_s, 5)),
            transport=transport,
        ) as client:
            resp = client.get("/models")
    except httpx.TimeoutException as exc:
        raise LLMTimeoutError("DeepSeek n'a pas répondu à temps (timeout)") from exc
    except httpx.HTTPError as exc:
        raise LLMUnavailableError(f"DeepSeek injoignable : {exc.__class__.__name__}") from exc
    if resp.status_code >= 400:
        raise _map_status(resp)
    try:
        data = resp.json()["data"]
        ids = [str(m["id"]).strip() for m in data if isinstance(m, dict) and str(m.get("id") or "").strip()]
    except (ValueError, KeyError, TypeError) as exc:
        raise LLMResponseError("liste des modèles DeepSeek illisible") from exc
    if not ids:
        raise LLMResponseError("DeepSeek n'a renvoyé aucun modèle")
    return list(dict.fromkeys(ids))


class DeepSeekModelCatalog:
    """Cache court de `fetch_models` (une seule clé et une seule adresse par moteur)."""

    ERROR_TTL_S = 30.0

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._value: tuple[str, list[str] | None, str | None] | None = None
        self._expires = 0.0

    def get(
        self,
        *,
        api_key: str,
        base_url: str,
        ttl_s: float,
        refresh: bool = False,
        transport: httpx.BaseTransport | None = None,
    ) -> tuple[list[str] | None, str | None]:
        """(identifiants, None) ou (None, raison de l'échec)."""
        with self._lock:
            if not refresh and self._value is not None and self._value[0] == base_url and self._clock() < self._expires:
                return self._value[1], self._value[2]
            try:
                ids: list[str] | None = fetch_models(api_key=api_key, base_url=base_url, transport=transport)
                error = None
            except LLMError as exc:
                ids, error = None, str(exc).replace(api_key, "***")
            self._value = (base_url, ids, error)
            self._expires = self._clock() + (ttl_s if ids else self.ERROR_TTL_S)
            return ids, error

    def clear(self) -> None:
        with self._lock:
            self._value = None

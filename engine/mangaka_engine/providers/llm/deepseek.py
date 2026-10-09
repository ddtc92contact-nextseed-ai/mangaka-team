"""Client DeepSeek (API compatible OpenAI : POST {base_url}/chat/completions)."""

from __future__ import annotations

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
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not api_key:
            raise LLMConfigError("DEEPSEEK_API_KEY manquante : renseigne-la dans .env ou utilise LLM_PROVIDER=mock")
        self.model = model
        self.temperature = temperature
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
            "temperature": self.temperature if temperature is None else temperature,
            "stream": False,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        try:
            resp = self._client.post("/chat/completions", json=payload)
        except httpx.TimeoutException as exc:
            raise LLMTimeoutError("DeepSeek n'a pas répondu à temps (timeout)") from exc
        except httpx.HTTPError as exc:
            raise LLMUnavailableError(f"DeepSeek injoignable : {exc.__class__.__name__}") from exc

        if resp.status_code >= 400:
            raise _map_status(resp)

        try:
            data = resp.json()
            text = data["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise LLMResponseError("réponse DeepSeek illisible") from exc
        if not isinstance(text, str):
            raise LLMResponseError("réponse DeepSeek sans contenu texte")
        usage = {k: v for k, v in (data.get("usage") or {}).items() if isinstance(v, int)}
        return LLMResult(text=text, model=data.get("model", self.model), usage=usage)

    def close(self) -> None:
        self._client.close()


def _api_message(resp: httpx.Response) -> str:
    try:
        err = resp.json().get("error")
        if isinstance(err, dict) and isinstance(err.get("message"), str):
            return err["message"]
    except ValueError:
        pass
    return ""


def _map_status(resp: httpx.Response) -> LLMError:
    status = resp.status_code
    detail = _api_message(resp)
    suffix = f" ({detail})" if detail else ""
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

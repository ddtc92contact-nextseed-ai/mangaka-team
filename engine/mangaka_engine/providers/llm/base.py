"""Interface commune des fournisseurs LLM texte."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol

Role = Literal["system", "user", "assistant"]


@dataclass
class ChatMessage:
    role: Role
    content: str


@dataclass
class LLMResult:
    text: str
    model: str
    usage: dict[str, int] = field(default_factory=dict)


class LLMError(Exception):
    """Erreur d'un fournisseur LLM, avec un message lisible par l'utilisateur."""

    code = "llm_error"
    retryable = False


class LLMConfigError(LLMError):
    code = "llm_config"


class LLMAuthError(LLMError):
    code = "llm_auth"


class LLMRateLimitError(LLMError):
    code = "llm_rate_limit"
    retryable = True


class LLMTimeoutError(LLMError):
    code = "llm_timeout"
    retryable = True


class LLMUnavailableError(LLMError):
    code = "llm_unavailable"
    retryable = True


class LLMBadRequestError(LLMError):
    code = "llm_bad_request"


class LLMResponseError(LLMError):
    code = "llm_bad_response"
    retryable = True


class LLMProvider(Protocol):
    name: str

    def complete(
        self,
        messages: list[ChatMessage],
        *,
        json_mode: bool = False,
        temperature: float | None = None,
    ) -> LLMResult: ...

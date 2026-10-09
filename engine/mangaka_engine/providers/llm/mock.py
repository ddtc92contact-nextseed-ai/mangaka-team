"""LLM factice, déterministe, sans réseau (mode par défaut sans .env et dans les tests)."""

from __future__ import annotations

import json
from collections.abc import Callable

from .base import ChatMessage, LLMResult

Responder = Callable[[list[ChatMessage], bool], str]


class MockLLMProvider:
    name = "mock"

    def __init__(self, responder: Responder | None = None) -> None:
        self._responder = responder
        self.calls: list[list[ChatMessage]] = []

    def complete(
        self,
        messages: list[ChatMessage],
        *,
        json_mode: bool = False,
        temperature: float | None = None,
    ) -> LLMResult:
        self.calls.append(messages)
        if self._responder is not None:
            text = self._responder(messages, json_mode)
        else:
            last = next((m.content for m in reversed(messages) if m.role == "user"), "")
            text = json.dumps({"mock": True, "echo": last}, ensure_ascii=False) if json_mode else f"[mock] {last}"
        return LLMResult(text=text, model="mock")

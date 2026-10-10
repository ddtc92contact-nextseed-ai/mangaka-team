"""Fournisseurs d'embeddings du savoir-faire (recherche vectorielle des passages).

- `mock` : vecteurs déterministes sans réseau (hachage des mots normalisés et de leurs préfixes) :
  deux textes qui partagent des mots sont proches. Mode par défaut, CI et QA ;
- `ollama` : `POST /api/embed` d'Ollama, modèle de `presets/providers.yaml` (`ollama.embedding_model`,
  suggestion : bge-m3, multilingue). Rien n'est téléchargé par le moteur : `ollama pull` à la main.

Chaque vecteur est enregistré avec `model_id` : un passage indexé par un autre modèle n'est pas
comparé (dimensions et espaces différents) tant qu'il n'a pas été réindexé.
"""

from __future__ import annotations

import hashlib
import math
import re
import unicodedata
from typing import Any, Protocol

import httpx


class EmbeddingError(Exception):
    """Erreur d'un fournisseur d'embeddings, avec un message lisible."""


class EmbeddingProvider(Protocol):
    name: str
    model_id: str  # « fournisseur:modèle », enregistré avec chaque vecteur

    def embed(self, texts: list[str]) -> list[list[float]]: ...


_WORD = re.compile(r"[a-z0-9]+")
# Mots vides français les plus fréquents (aussi utilisés par la recherche par mots-clés).
STOPWORDS = frozenset(
    [
        "au",
        "aux",
        "avec",
        "ce",
        "ces",
        "dans",
        "de",
        "des",
        "du",
        "elle",
        "en",
        "et",
        "eux",
        "il",
        "ils",
        "je",
        "la",
        "le",
        "les",
        "leur",
        "lui",
        "ma",
        "mais",
        "me",
        "meme",
        "mes",
        "moi",
        "mon",
        "ne",
        "nos",
        "notre",
        "nous",
        "on",
        "ou",
        "par",
        "pas",
        "pour",
        "qu",
        "que",
        "qui",
        "sa",
        "se",
        "ses",
        "son",
        "sur",
        "ta",
        "te",
        "tes",
        "toi",
        "ton",
        "tu",
        "un",
        "une",
        "vos",
        "votre",
        "vous",
        "c",
        "d",
        "j",
        "l",
        "m",
        "n",
        "s",
        "t",
        "y",
        "a",
        "est",
        "sont",
        "ete",
        "etre",
        "avoir",
        "fait",
        "faire",
        "plus",
        "tres",
        "tout",
        "tous",
        "toute",
        "toutes",
        "comme",
        "si",
        "quand",
        "comment",
        "quoi",
        "dont",
        "the",
        "and",
        "of",
        "to",
        "in",
        "is",
        "it",
        "for",
        "on",
        "with",
    ]
)


def normalize_words(text: str) -> list[str]:
    """Mots en minuscules sans accents ni mots vides (« Décors ! » → ["decors"])."""
    plain = unicodedata.normalize("NFKD", text.casefold())
    plain = "".join(c for c in plain if not unicodedata.combining(c))
    return [w for w in _WORD.findall(plain) if len(w) > 1 and w not in STOPWORDS]


class MockEmbeddingProvider:
    """Sac de mots haché (et préfixes de 5 lettres, pour rapprocher « rythme » et « rythmes »), normalisé L2."""

    name = "mock"

    def __init__(self, dim: int = 256) -> None:
        self.dim = dim
        self.model_id = f"mock:hash-{dim}"
        self.calls = 0

    def _bucket(self, feature: str) -> tuple[int, float]:
        h = hashlib.blake2b(feature.encode(), digest_size=8).digest()
        return int.from_bytes(h[:4], "little") % self.dim, (1.0 if h[4] & 1 else -1.0)

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls += 1
        out = []
        for text in texts:
            vec = [0.0] * self.dim
            for word in normalize_words(text):
                for feature, weight in ((word, 1.0), (f"~{word[:5]}", 0.5)):
                    i, sign = self._bucket(feature)
                    vec[i] += sign * weight
            norm = math.sqrt(sum(v * v for v in vec))
            out.append([v / norm for v in vec] if norm else vec)
        return out


class OllamaEmbeddingProvider:
    name = "ollama"

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        num_ctx: int | None = None,
        timeout_s: float = 120,
        batch_size: int = 32,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.model_id = f"ollama:{model}"
        self.num_ctx = num_ctx
        self.batch_size = batch_size
        self._client = httpx.Client(
            base_url=self.base_url,
            timeout=httpx.Timeout(timeout_s, connect=min(timeout_s, 5)),
            transport=transport,
        )

    def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):
            out += self._embed(texts[start : start + self.batch_size])
        return out

    def _embed(self, texts: list[str]) -> list[list[float]]:
        payload: dict[str, Any] = {"model": self.model, "input": texts}
        if self.num_ctx is not None:
            payload["options"] = {"num_ctx": self.num_ctx}
        try:
            resp = self._client.post("/api/embed", json=payload)
        except httpx.TimeoutException as exc:
            raise EmbeddingError(f"Ollama n'a pas répondu à temps ({self.model})") from exc
        except httpx.HTTPError as exc:
            raise EmbeddingError(
                f"Ollama injoignable sur {self.base_url} : lance « ollama serve » (ou EMBEDDING_PROVIDER=mock)"
            ) from exc
        if resp.status_code == 404:
            raise EmbeddingError(f"modèle {self.model} absent d'Ollama : lance « ollama pull {self.model} »")
        if resp.status_code >= 400:
            raise EmbeddingError(f"Ollama a répondu {resp.status_code} : {resp.text[:200]}")
        try:
            vectors = resp.json()["embeddings"]
        except (ValueError, KeyError, TypeError) as exc:
            raise EmbeddingError("réponse d'Ollama illisible (embeddings)") from exc
        if not isinstance(vectors, list) or len(vectors) != len(texts):
            raise EmbeddingError("Ollama n'a pas renvoyé un vecteur par passage")
        return [[float(x) for x in v] for v in vectors]


__all__ = [
    "STOPWORDS",
    "EmbeddingError",
    "EmbeddingProvider",
    "MockEmbeddingProvider",
    "OllamaEmbeddingProvider",
    "normalize_words",
]

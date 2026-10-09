"""Messages de validation Pydantic en français (API et sorties du LLM)."""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError


def _num(value: Any) -> str:
    return f"{value:g}" if isinstance(value, float) else str(value)


def translate_error(err: dict[str, Any]) -> str:
    kind = err.get("type", "")
    ctx = err.get("ctx") or {}
    match kind:
        case "missing":
            return "champ obligatoire"
        case "string_too_short":
            n = ctx.get("min_length", 1)
            return "ne doit pas être vide" if n == 1 else f"au moins {n} caractères"
        case "string_too_long":
            return f"au plus {ctx.get('max_length')} caractères"
        case "too_short":
            return f"au moins {ctx.get('min_length')} élément(s)"
        case "too_long":
            return f"au plus {ctx.get('max_length')} éléments"
        case "literal_error" | "enum":
            return f"valeur non autorisée (attendu : {ctx.get('expected', '?')})"
        case "greater_than_equal":
            return f"doit être supérieur ou égal à {_num(ctx.get('ge'))}"
        case "less_than_equal":
            return f"doit être inférieur ou égal à {_num(ctx.get('le'))}"
        case "greater_than":
            return f"doit être strictement supérieur à {_num(ctx.get('gt'))}"
        case "less_than":
            return f"doit être strictement inférieur à {_num(ctx.get('lt'))}"
        case "int_parsing" | "int_type" | "float_parsing" | "float_type" | "int_from_float":
            return "nombre attendu"
        case "string_type":
            return "texte attendu"
        case "list_type":
            return "liste attendue"
        case "bool_parsing" | "bool_type":
            return "booléen attendu"
        case "json_invalid":
            return "JSON invalide"
        case "model_attributes_type" | "dict_type":
            return "objet JSON attendu"
        case "extra_forbidden":
            return "champ inconnu"
        case "value_error":
            return str(err.get("msg", "")).removeprefix("Value error, ")
    return str(err.get("msg", "valeur invalide"))


def format_errors(exc: ValidationError, labels: dict[str, str] | None = None, limit: int = 8) -> str:
    """« page 1 › case 2 › shot_type : valeur non autorisée (…) ; … » — indices affichés à partir de 1."""
    labels = labels or {}
    parts: list[str] = []
    for err in exc.errors()[:limit]:
        raw = list(err.get("loc", ()))
        loc: list[str] = []
        i = 0
        while i < len(raw):
            item = raw[i]
            nxt = raw[i + 1] if i + 1 < len(raw) else None
            if isinstance(item, str) and item in labels and isinstance(nxt, int):
                loc.append(f"{labels[item]} {nxt + 1}")
                i += 2
                continue
            loc.append(str(item))
            i += 1
        parts.append(f"{' › '.join(loc) or '(racine)'} : {translate_error(err)}")
    extra = len(exc.errors()) - limit
    if extra > 0:
        parts.append(f"… et {extra} autre(s) erreur(s)")
    return " ; ".join(parts)

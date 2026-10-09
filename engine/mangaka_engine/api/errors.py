"""Erreurs HTTP lisibles : 422 détaillées en français, jamais de stack trace côté client."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("mangaka_engine")


class FieldError(Exception):
    """Erreur métier sur un champ, rendue comme une 422 de validation."""

    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field = field
        self.message = message


def _num(value: Any) -> str:
    return f"{value:g}" if isinstance(value, float) else str(value)


def _translate(err: dict[str, Any]) -> str:
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


def _field(loc: tuple[Any, ...] | list[Any]) -> str:
    parts = list(loc)
    if parts and parts[0] in ("body", "query", "path", "form", "header"):
        parts = parts[1:]
    return ".".join(str(p) for p in parts) or "requête"


def _invalid(errors: list[dict[str, str]]) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": "Données invalides", "errors": errors})


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        return _invalid([{"field": _field(e.get("loc", ())), "message": _translate(e)} for e in exc.errors()])

    @app.exception_handler(FieldError)
    async def _field_error(_: Request, exc: FieldError) -> JSONResponse:
        return _invalid([{"field": exc.field, "message": exc.message}])

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        detail = exc.detail
        if exc.status_code == 404 and detail == "Not Found":
            detail = "Ressource introuvable"
        elif exc.status_code == 405 and detail == "Method Not Allowed":
            detail = "Méthode non autorisée"
        return JSONResponse(status_code=exc.status_code, content={"detail": detail}, headers=exc.headers)

    @app.exception_handler(Exception)
    async def _unexpected(_: Request, exc: Exception) -> JSONResponse:
        log.exception("erreur interne", exc_info=exc)
        return JSONResponse(status_code=500, content={"detail": "Erreur interne du moteur"})

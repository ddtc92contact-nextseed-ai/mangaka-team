"""Erreurs HTTP lisibles : 422 détaillées en français, jamais de stack trace côté client."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from ..validation import translate_error as _translate

log = logging.getLogger("mangaka_engine")


class FieldError(Exception):
    """Erreur métier sur un champ, rendue comme une 422 de validation."""

    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field = field
        self.message = message


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

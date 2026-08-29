"""Safe application exceptions and FastAPI exception handlers."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class DriftGuardError(Exception):
    def __init__(
        self,
        *,
        code: str,
        message: str,
        status_code: int = 400,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}


def _error_body(
    code: str, message: str, details: dict[str, Any] | list[Any] | None = None
) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "details": details or {}}}


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(DriftGuardError)
    async def handle_driftguard_error(_request: Request, exc: DriftGuardError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_body(exc.code, exc.message, exc.details),
        )

    @app.exception_handler(RequestValidationError)
    async def handle_request_validation(
        _request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        safe_details = [
            {"location": list(error["loc"]), "message": error["msg"]} for error in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content=_error_body(
                "request_validation_error", "The request is invalid.", safe_details
            ),
        )

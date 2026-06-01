"""Domain exceptions + the HTTP error-handling layer (the app's "middleware" for errors).

The service and repository layers raise these framework-agnostic exceptions; the FastAPI
app maps them to status codes once, here, via `register_exception_handlers` — so routers
stay thin and never repeat try/except. The MCP server catches the same exceptions and
turns them into tool errors. Status mapping rides the class hierarchy (Starlette resolves
a handler by the exception's MRO), so a handler on the base catches its subclasses.
"""

from __future__ import annotations


class DoenError(Exception):
    """Base for all Doen domain errors."""


class NotFoundError(DoenError):
    """A requested entity does not exist -> 404."""


class ValidationError(DoenError):
    """Input or a business rule was violated -> 422."""


class ConflictError(DoenError):
    """The operation conflicts with the current state -> 409."""


class StaleSpecError(ConflictError):
    """Optimistic-lock miss: the spec changed under the writer -> 409."""

    def __init__(self, initiative_id: str, expected: int, found: int):
        super().__init__(
            f"spec {initiative_id} changed under you (have v{expected}, db v{found})"
        )
        self.initiative_id, self.expected, self.found = initiative_id, expected, found


class InvalidStageTransition(ValidationError):
    """An initiative was asked to jump stages — only one step (fwd/back) is legal -> 422."""

    def __init__(self, initiative_id: str, current: str, target: str):
        super().__init__(
            f"initiative {initiative_id}: {current} -> {target} is not a one-step lifecycle move"
        )
        self.initiative_id, self.current, self.target = initiative_id, current, target


class InvalidTransition(ValidationError):
    """A work unit was asked to make a status change the state machine forbids -> 422."""

    def __init__(self, unit_id: str, current: str, target: str):
        super().__init__(
            f"work unit {unit_id}: {current} -> {target} is not a legal transition"
        )
        self.unit_id, self.current, self.target = unit_id, current, target


class DecisionTimeout(DoenError):
    """wait_for_decision timed out — surfaced over MCP only, no HTTP mapping."""


def register_exception_handlers(app) -> None:
    """Map domain exceptions to HTTP responses, once, app-wide. Imported lazily so the
    exception classes stay framework-agnostic for the MCP server and unit tests."""
    from asyncpg.exceptions import ForeignKeyViolationError
    from fastapi import Request
    from fastapi.responses import JSONResponse

    from app.providers.llm import LLMError

    def _json(status: int, detail: str) -> JSONResponse:
        return JSONResponse(status_code=status, content={"detail": detail})

    @app.exception_handler(NotFoundError)
    async def _not_found(_: Request, exc: NotFoundError):
        return _json(404, str(exc))

    @app.exception_handler(ConflictError)
    async def _conflict(_: Request, exc: ConflictError):
        return _json(409, str(exc))

    @app.exception_handler(ValidationError)
    async def _validation(_: Request, exc: ValidationError):
        return _json(422, str(exc))

    @app.exception_handler(ForeignKeyViolationError)
    async def _fk(_: Request, exc: ForeignKeyViolationError):
        return _json(404, "referenced entity does not exist")

    @app.exception_handler(LLMError)
    async def _llm(_: Request, exc: LLMError):
        return _json(502, f"shaping failed: {exc}")

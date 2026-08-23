"""Request-local tenant identity shared by hosted JARVIS services."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from collections.abc import Iterator


_current_user_id: ContextVar[str | None] = ContextVar(
    "jarvis_current_user_id",
    default=None,
)


def get_current_user_id() -> str | None:
    return _current_user_id.get()


@contextmanager
def tenant_scope(user_id: str) -> Iterator[None]:
    token = _current_user_id.set(str(user_id))
    try:
        yield
    finally:
        _current_user_id.reset(token)

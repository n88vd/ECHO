from fastapi import HTTPException

from app.core.auth import CurrentUser, CurrentUserDep  # noqa: F401


def not_found(what: str = "not found") -> HTTPException:
    return HTTPException(404, what)

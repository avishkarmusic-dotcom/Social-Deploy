"""Errors that tell the person what to do next.

Every AppError carries three things: a stable machine `code` for the client to
branch on, a `message` describing what happened, and a `fix` describing what to
do about it. The fix field is not decoration — it is the difference between
"403 Forbidden" and "Reconnect Gmail in Settings → Channels."

Nothing here apologises. A user who hit a rate limit doesn't need contrition,
they need to know it clears in forty seconds.
"""
from __future__ import annotations


class AppError(Exception):
    status_code: int = 400
    code: str = "bad_request"

    def __init__(self, message: str, *, fix: str = "", code: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.fix = fix
        if code:
            self.code = code


class NotFound(AppError):
    status_code = 404
    code = "not_found"

    def __init__(self, resource: str, identifier: str = "") -> None:
        super().__init__(
            f"That {resource} doesn't exist, or isn't in this workspace.",
            fix="Check the link — it may point at a workspace you've since left.",
        )
        self.resource = resource
        self.identifier = identifier


class Unauthorized(AppError):
    status_code = 401
    code = "unauthorized"

    def __init__(self, message: str = "Your session has expired.") -> None:
        super().__init__(message, fix="Sign in again.")


class Forbidden(AppError):
    status_code = 403
    code = "forbidden"

    def __init__(self, action: str, required_role: str = "admin") -> None:
        super().__init__(
            f"Your role doesn't allow you to {action}.",
            fix=f"Ask a workspace {required_role} to do this, or to change your role.",
        )


class Conflict(AppError):
    status_code = 409
    code = "conflict"


class RateLimited(AppError):
    status_code = 429
    code = "rate_limited"

    def __init__(self, retry_after_s: int) -> None:
        super().__init__(
            "You're sending requests faster than this workspace's limit.",
            fix=f"Requests resume in about {retry_after_s} seconds. Nothing is lost.",
        )
        self.retry_after_s = retry_after_s


class ValidationFailed(AppError):
    status_code = 422
    code = "validation_failed"


class UpstreamUnavailable(AppError):
    status_code = 502
    code = "upstream_unavailable"

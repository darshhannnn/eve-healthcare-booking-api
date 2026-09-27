"""Domain errors raised by services; translated to HTTP responses in ``main.py``.

Keeping the HTTP mapping in one place lets services stay framework-agnostic
and makes the error contract uniform across the API.
"""


class AppError(Exception):
    status_code = 400
    default_detail = "Bad request"

    def __init__(self, detail: str | None = None) -> None:
        self.detail = detail or self.default_detail
        super().__init__(self.detail)


class BadRequestError(AppError):
    status_code = 400
    default_detail = "Bad request"


class UnauthenticatedError(AppError):
    status_code = 401
    default_detail = "Not authenticated"


class ForbiddenError(AppError):
    status_code = 403
    default_detail = "You do not have permission to perform this action"


class NotFoundError(AppError):
    status_code = 404
    default_detail = "Resource not found"


class ConflictError(AppError):
    status_code = 409
    default_detail = "Conflict with the current state of the resource"


class UnprocessableError(AppError):
    status_code = 422
    default_detail = "Request could not be processed"

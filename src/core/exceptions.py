class AppError(Exception):
    """Base class for application-specific exceptions."""

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


class NotFoundError(AppError):
    """Exception raised when a requested resource is not found."""

    def __init__(self, message: str = "Resource not found"):
        super().__init__(message)


class ConflictError(AppError):
    """Exception raised when there is a conflict with the current state of the resource."""

    def __init__(self, message: str = "Conflict with the current state of the resource"):
        super().__init__(message)


class ValidationError(AppError):
    """Exception raised for validation errors."""

    def __init__(self, message: str = "Validation error"):
        super().__init__(message)


class UnauthorizedError(AppError):
    """Exception raised for unauthorized access."""

    def __init__(self, message: str = "Invalid authentication credentials"):
        super().__init__(message)


class RateLimitExceededError(AppError):
    """Exception raised when a client exceeds the allowed rate limit."""

    def __init__(
        self,
        message: str = "Rate limit exceeded. Please retry later.",
        *,
        retry_after: float = 1.0,
        limit: int = 100,
        remaining: int = 0,
        reset: int = 1,
    ):
        super().__init__(message)
        self.retry_after = retry_after
        self.limit = limit
        self.remaining = remaining
        self.reset = reset

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

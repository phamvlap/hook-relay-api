from src.core.exceptions import AppError


class InvalidAPIKeyFormatError(AppError):
    """Exception raised when an invalid API key is provided."""

    def __init__(self, message: str = "Invalid API key"):
        super().__init__(message)

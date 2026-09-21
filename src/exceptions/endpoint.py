from src.core.exceptions import NotFoundError, ValidationError


class EndpointNotFoundError(NotFoundError):
    pass


class EndpointValidationError(ValidationError):
    """Exception raised for validation errors related to endpoints."""

    def __init__(self, message: str = "Endpoint validation error"):
        self.message = message
        super().__init__(message)

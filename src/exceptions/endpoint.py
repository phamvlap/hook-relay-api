from src.core.exceptions import ConflictError, NotFoundError, ValidationError


class EndpointNotFoundError(NotFoundError):
    pass


class EndpointValidationError(ValidationError):
    """Exception raised for validation errors related to endpoints."""

    def __init__(self, message: str = "Invalid endpoint data provided"):
        super().__init__(message)


class EndpointConflictError(ConflictError):
    """Exception raised for conflicts related to endpoints."""

    def __init__(self, message: str = "An endpoint with the same name or URL already exists"):
        super().__init__(message)

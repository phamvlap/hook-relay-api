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


class EndpointSecretConflictError(ConflictError):
    """Exception raised for conflicts related to endpoint secrets."""

    def __init__(self, message: str = "An endpoint secret with the same version already exists"):
        super().__init__(message)

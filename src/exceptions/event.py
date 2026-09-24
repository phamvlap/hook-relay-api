from src.core.exceptions import ConflictError, NotFoundError, ValidationError


class EventNotFoundError(NotFoundError):
    pass


class EventValidationError(ValidationError):
    def __init__(self, message: str = "Event validation error") -> None:
        super().__init__(message)


class EventConflictError(ConflictError):
    def __init__(self, message: str = "Event conflict error") -> None:
        super().__init__(message)

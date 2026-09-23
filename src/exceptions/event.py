from src.core.exceptions import NotFoundError, ValidationError


class EventNotFoundError(NotFoundError):
    pass


class EventValidationError(ValidationError):
    def __init__(self, message: str = "Event validation error") -> None:
        super().__init__(message)

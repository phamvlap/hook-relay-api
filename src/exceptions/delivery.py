from src.core.exceptions import ConflictError, NotFoundError


class DeliveryNotFoundError(NotFoundError):
    pass


class DeliveryNotEligibleForRetryError(ConflictError):
    """Exception raised when attempting to manually retry a delivery not in dead_letter status."""

    def __init__(
        self,
        message: str = "Only deliveries in 'dead_letter' status can be manually retried.",
    ):
        super().__init__(message)

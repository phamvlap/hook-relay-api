from abc import ABC, abstractmethod


class BackoffStrategy(ABC):
    """Abstract base class for calculating deterministic backoff delay."""

    @abstractmethod
    def calculate(self, attempt: int) -> float:
        """Calculate base delay in seconds for a given attempt index (0-indexed)."""


class FixedBackoff(BackoffStrategy):
    """Always returns a constant delay."""

    def __init__(self, delay: float = 5.0) -> None:
        self.delay = max(0.0, delay)

    def calculate(self, attempt: int) -> float:
        return self.delay


class LinearBackoff(BackoffStrategy):
    """Delay increases linearly: base_delay * (attempt + 1)."""

    def __init__(self, base_delay: float = 2.0, max_delay: float = 300.0) -> None:
        self.base_delay = max(0.0, base_delay)
        self.max_delay = max(self.base_delay, max_delay)

    def calculate(self, attempt: int) -> float:
        delay = self.base_delay * (attempt + 1)
        return min(delay, self.max_delay)


class ExponentialBackoff(BackoffStrategy):
    """Exponential backoff: base_delay * (factor ** attempt)."""

    def __init__(
        self,
        base_delay: float = 2.0,
        factor: float = 2.0,
        max_delay: float = 3600.0,
    ) -> None:
        self.base_delay = max(0.0, base_delay)
        self.factor = max(1.0, factor)
        self.max_delay = max(self.base_delay, max_delay)

    def calculate(self, attempt: int) -> float:
        delay = self.base_delay * (self.factor**attempt)
        return min(delay, self.max_delay)

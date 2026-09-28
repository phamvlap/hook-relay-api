import random
from abc import ABC, abstractmethod

from src.core.retry.enums import JitterType


class JitterStrategy(ABC):
    """Abstract base class for jitter calculation."""

    @abstractmethod
    def apply(self, delay: float, base_delay: float = 1.0) -> float:
        """Apply jitter algorithm to computed backoff delay."""


class NoJitter(JitterStrategy):
    """Deterministic delay without randomization. Perfect for testing."""

    def apply(self, delay: float, base_delay: float = 1.0) -> float:
        return max(0.0, delay)


class FullJitter(JitterStrategy):
    """Full Jitter: Uniform random between 0 and delay: U(0, delay).

    Maximally de-synchronizes concurrent requests across the entire window.
    """

    def apply(self, delay: float, base_delay: float = 1.0) -> float:
        if delay <= 0:
            return 0.0
        return random.uniform(0.0, delay)


class EqualJitter(JitterStrategy):
    """Equal Jitter: Guarantees half the backoff sleep while randomizing the remainder:

    delay / 2 + U(0, delay / 2).
    """

    def apply(self, delay: float, base_delay: float = 1.0) -> float:
        if delay <= 0:
            return 0.0
        half = delay / 2.0
        return half + random.uniform(0.0, half)


class AdditiveJitter(JitterStrategy):
    """Additive Jitter: Adds bounded random jitter to the calculated delay:

    delay + U(0, max_jitter).
    Default max_jitter is min(base_delay, 1.0s) unless explicitly overridden.
    """

    def __init__(self, max_jitter: float | None = None) -> None:
        self.max_jitter = max(0.0, max_jitter) if max_jitter is not None else None

    def apply(self, delay: float, base_delay: float = 1.0) -> float:
        ceiling = self.max_jitter if self.max_jitter is not None else min(base_delay, 1.0)
        return max(0.0, delay + random.uniform(0.0, max(0.0, ceiling)))


def create_jitter_strategy(
    jitter_type: JitterType | str,
    max_additive_jitter: float | None = None,
) -> JitterStrategy:
    """Factory helper to build a JitterStrategy from enum or string value."""
    normalized_type = JitterType(jitter_type) if isinstance(jitter_type, str) else jitter_type

    jitter_strategy_map = {
        JitterType.NONE: NoJitter,
        JitterType.FULL: FullJitter,
        JitterType.EQUAL: EqualJitter,
        JitterType.ADDITIVE: lambda: AdditiveJitter(max_jitter=max_additive_jitter),
    }

    return jitter_strategy_map.get(normalized_type, NoJitter)()

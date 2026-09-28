from src.core.enum import BaseStrEnum


class JitterType(BaseStrEnum):
    NONE = "none"
    FULL = "full"
    EQUAL = "equal"
    ADDITIVE = "additive"


class BackoffType(BaseStrEnum):
    FIXED = "fixed"
    LINEAR = "linear"
    EXPONENTIAL = "exponential"

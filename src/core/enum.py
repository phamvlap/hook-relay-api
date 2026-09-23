from enum import StrEnum


class BaseStrEnum(StrEnum):
    @classmethod
    def values(cls) -> tuple[str, ...]:
        return tuple(member.value for member in cls)

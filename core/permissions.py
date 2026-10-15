"""Permission policy for actions performed by the personal assistant."""

from enum import Enum


class PermissionLevel(str, Enum):
    """Risk tiers used by tools before they can perform an action."""

    READ_ONLY = "read_only"
    SAFE = "safe"
    CONFIRM = "confirm"


class ConfirmationRequiredError(PermissionError):
    """Raised when a non-reversible action was not explicitly confirmed."""


class PermissionPolicy:
    """Small, explicit policy independent of the LLM or desktop environment."""

    def require(self, level: PermissionLevel, confirmed: bool = False) -> None:
        if level is PermissionLevel.CONFIRM and not confirmed:
            raise ConfirmationRequiredError(
                "This action can change or close a window and needs confirmation."
            )

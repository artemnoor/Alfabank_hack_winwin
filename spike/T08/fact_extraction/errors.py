"""Sanitized errors for the experimental extraction spike."""


class ExtractionValidationError(ValueError):
    """An input or model extraction violates the spike's safe invariants."""


class LiveCallsDisabled(RuntimeError):
    """Paid provider calls are disabled until explicit user authorization."""


class LiveCallBudgetExceeded(RuntimeError):
    """The per-adapter request allowance has been exhausted."""


class ExtractionProviderError(RuntimeError):
    """A provider failure represented without body, prompt, or payload data."""

    def __init__(self, code: str, *, status_code: int | None = None) -> None:
        self.code = code
        self.status_code = status_code
        super().__init__(code)

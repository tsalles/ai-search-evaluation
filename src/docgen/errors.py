from docgen.models import Usage


class InputError(ValueError):
    """Invalid public input."""


class IntegrityError(RuntimeError):
    """Corrupted state, mismatched identity, or unsafe persistence."""


class ProviderError(RuntimeError):
    """Safe, typed model-provider failure; raw HTTP bodies are never the message."""

    def __init__(
        self, code: str, message: str, *, retryable: bool = False,
        usage: Usage | None = None, request_id: str | None = None,
        retry_after_seconds: float | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.usage = usage
        self.request_id = request_id
        self.retry_after_seconds = retry_after_seconds

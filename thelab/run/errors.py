"""Run-specific exceptions."""


class RejectedRunError(Exception):
    """Raised when a run is rejected due to invalid input, schema, or validation."""

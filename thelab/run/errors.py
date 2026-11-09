"""Run-specific exceptions."""


class RejectedRunError(ValueError):
    """Raised when a run is rejected due to invalid input, schema, or validation.

    Subclasses ``ValueError`` so programmatic callers that expect invalid-input
    errors (and pytest.raises(ValueError) contracts) keep working unchanged.
    """

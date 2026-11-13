"""Errors that stop the joke before it can keep spending."""


class EatTokensError(Exception):
    """Base error. Details must already be safe to print."""


class ConfigError(EatTokensError):
    """The user (or the defaults) asked for something we will not run."""


class ProviderError(EatTokensError):
    """The provider call failed or returned something we will not trust.

    billed_unknown is true when the request may already have been billed
    but the response had no usable usage object. The loop counts one
    conservative bite and stops. It does not try again.
    """

    def __init__(self, message: str, billed_unknown: bool = False) -> None:
        super().__init__(message)
        self.billed_unknown = billed_unknown

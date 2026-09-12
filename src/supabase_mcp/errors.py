"""Internal errors with messages that are safe to return to MCP clients."""


class SafeMCPError(Exception):
    """An expected error whose code and message contain no sensitive details."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.safe_message = message


class InvalidSelectionError(SafeMCPError):
    """A selection request failed allowlist or metadata validation."""


class DatabaseConfigurationError(RuntimeError):
    """Database configuration or startup validation failed."""

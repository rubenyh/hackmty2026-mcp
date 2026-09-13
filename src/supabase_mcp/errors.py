"""Internal errors and the stable public taxonomy used by MCP tools."""

from __future__ import annotations

from enum import StrEnum


class PublicErrorCode(StrEnum):
    """Bounded error codes that are safe and actionable for MCP clients."""

    VALIDATION_ERROR = "VALIDATION_ERROR"
    INVALID_DATE_RANGE = "INVALID_DATE_RANGE"
    INVALID_CURSOR = "INVALID_CURSOR"
    USER_SCOPE_ERROR = "USER_SCOPE_ERROR"
    NOT_FOUND = "NOT_FOUND"
    DATABASE_UNAVAILABLE = "DATABASE_UNAVAILABLE"
    DATABASE_TIMEOUT = "DATABASE_TIMEOUT"
    DATABASE_PERMISSION_ERROR = "DATABASE_PERMISSION_ERROR"
    DATABASE_QUERY_ERROR = "DATABASE_QUERY_ERROR"
    DATA_MAPPING_ERROR = "DATA_MAPPING_ERROR"
    INFERENCE_NOT_CONFIGURED = "INFERENCE_NOT_CONFIGURED"
    INFERENCE_TIMEOUT = "INFERENCE_TIMEOUT"
    INFERENCE_UNAVAILABLE = "INFERENCE_UNAVAILABLE"
    INFERENCE_AUTH_ERROR = "INFERENCE_AUTH_ERROR"
    INFERENCE_VERSION_MISMATCH = "INFERENCE_VERSION_MISMATCH"
    INFERENCE_CONTRACT_ERROR = "INFERENCE_CONTRACT_ERROR"
    INFERENCE_RESPONSE_ERROR = "INFERENCE_RESPONSE_ERROR"
    INTERNAL_ERROR = "INTERNAL_ERROR"


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

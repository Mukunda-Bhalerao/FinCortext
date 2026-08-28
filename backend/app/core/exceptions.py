"""Domain exceptions for FinCortext.

External provider failures must be translated into these domain errors so
that API handlers and agents can respond gracefully and specifically.
"""

from __future__ import annotations


class FinCortextError(Exception):
    """Base class for all FinCortext domain errors."""

    code = "fincortext_error"
    http_status = 500

    def __init__(self, message: str, *, details: dict | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def to_dict(self) -> dict:
        return {"code": self.code, "message": self.message, "details": self.details}


class ConfigurationError(FinCortextError):
    """Required configuration is missing or invalid."""

    code = "configuration_error"
    http_status = 500


class ProviderError(FinCortextError):
    """An external data provider failed (network, API, parsing, ...)."""

    code = "provider_error"
    http_status = 502


class ProviderUnavailableError(ProviderError):
    """A provider is not configured or unreachable (e.g. missing API key)."""

    code = "provider_unavailable"
    http_status = 503


class ValidationError(FinCortextError):
    """Input data failed validation."""

    code = "validation_error"
    http_status = 422

    def __init__(self, message: str, *, errors: list | None = None, details: dict | None = None) -> None:
        super().__init__(message, details=details)
        self.errors = errors or []


class NotFoundError(FinCortextError):
    """A requested entity does not exist."""

    code = "not_found"
    http_status = 404


class IngestionError(FinCortextError):
    """A file/document could not be ingested."""

    code = "ingestion_error"
    http_status = 422


class UnsupportedFormatError(IngestionError):
    """The uploaded file format is not supported."""

    code = "unsupported_format"
    http_status = 415


class StorageError(FinCortextError):
    """A storage operation failed."""

    code = "storage_error"
    http_status = 500


class AgentError(FinCortextError):
    """An agent failed to produce a valid output."""

    code = "agent_error"
    http_status = 500


class ModelUnavailableError(ProviderUnavailableError):
    """The local sentiment model is unavailable (not downloaded / load error)."""

    code = "model_unavailable"
    http_status = 503
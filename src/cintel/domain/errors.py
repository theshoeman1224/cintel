"""Typed application errors."""


class CintelError(Exception):
    """Base class for expected application failures."""


class ConfigurationError(CintelError):
    """Configuration is missing or invalid."""


class InitializationError(CintelError):
    """A repository workspace could not be initialized safely."""


class StorageError(CintelError):
    """Persistent analysis state could not be accessed."""


class FeatureNotImplementedError(CintelError):
    """A planned adapter or workflow is not implemented in this release."""


class AIUnavailableError(CintelError):
    """AI functionality was requested while AI support is disabled."""


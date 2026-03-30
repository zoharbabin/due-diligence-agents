"""DealConfig loader and validation.

Reads deal-config.json, validates against the Pydantic DealConfig model,
and returns a typed configuration object for the rest of the pipeline.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from dd_agents.models.config import DealConfig

logger = logging.getLogger(__name__)

# UTF-8 BOM prefix (byte-order mark)
_UTF8_BOM = "\ufeff"


class ConfigError(Exception):
    """Base exception for configuration loading errors."""


class ConfigFileNotFoundError(ConfigError):
    """Raised when the config file does not exist."""


class ConfigParseError(ConfigError):
    """Raised when the config file contains invalid JSON."""


class ConfigValidationError(ConfigError):
    """Raised when the config data fails Pydantic validation.

    Attributes:
        validation_error: The underlying Pydantic ``ValidationError``.
    """

    def __init__(self, message: str, validation_error: ValidationError) -> None:
        super().__init__(message)
        self.validation_error = validation_error


def load_deal_config(path: Path) -> DealConfig:
    """Load and validate a deal configuration from a JSON file.

    Parameters
    ----------
    path:
        Filesystem path to the ``deal-config.json`` file.

    Returns
    -------
    DealConfig
        A fully-validated Pydantic model instance.

    Raises
    ------
    ConfigFileNotFoundError
        If *path* does not point to an existing file.
    ConfigParseError
        If the file content is not valid JSON.
    ConfigValidationError
        If the parsed JSON fails DealConfig Pydantic validation.
    """
    resolved = Path(path).resolve()

    if not resolved.is_file():
        raise ConfigFileNotFoundError(f"Config file not found: {resolved}")

    logger.debug("Loading deal config from %s", resolved)

    try:
        raw = resolved.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigFileNotFoundError(f"Cannot read config file: {resolved}: {exc}") from exc

    # Strip UTF-8 BOM if present
    if raw.startswith(_UTF8_BOM):
        raw = raw[len(_UTF8_BOM) :]
        logger.debug("Stripped UTF-8 BOM from config file")

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ConfigParseError(f"Invalid JSON in config file {resolved}: {exc}") from exc

    if not isinstance(data, dict):
        raise ConfigParseError(f"Config file must contain a JSON object, got {type(data).__name__}")

    return validate_deal_config(data)


def validate_deal_config(data: dict[str, Any]) -> DealConfig:
    """Validate a dict against the DealConfig Pydantic model.

    This is useful when the caller already has parsed JSON data (e.g. from
    an API request or an in-memory fixture) and wants validation without
    going through the filesystem.

    Parameters
    ----------
    data:
        A dictionary representing the deal configuration.

    Returns
    -------
    DealConfig
        A fully-validated Pydantic model instance.

    Raises
    ------
    ConfigValidationError
        If *data* fails DealConfig validation.  The wrapped
        ``validation_error`` attribute contains the Pydantic
        ``ValidationError`` with per-field details.
    """
    try:
        return DealConfig.model_validate(data)
    except ValidationError as exc:
        error_count = exc.error_count()
        summary = f"Deal config validation failed with {error_count} error(s):\n"
        for err in exc.errors():
            loc = " -> ".join(str(part) for part in err["loc"])
            summary += f"  - {loc}: {err['msg']}\n"
        raise ConfigValidationError(summary, validation_error=exc) from exc

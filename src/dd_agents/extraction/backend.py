"""Pluggable extraction backend protocol and fallback chain.

Defines the ``ExtractionBackend`` protocol for implementing custom
document extractors and ``ExtractionChain`` for configurable fallback
chains.  Existing extractors (markitdown, ocr, glm_ocr) satisfy the
protocol through structural subtyping — no code changes needed in the
extractor classes beyond adding ``name`` and ``supported_extensions``
properties.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)


@runtime_checkable
class ExtractionBackend(Protocol):
    """Protocol for pluggable document extractors.

    Any class with ``name``, ``supported_extensions``, and ``extract``
    satisfies this protocol via structural subtyping.
    """

    @property
    def name(self) -> str:
        """Human-readable backend identifier (e.g. ``"markitdown"``)."""
        ...

    @property
    def supported_extensions(self) -> frozenset[str]:
        """File extensions this backend can handle (e.g. ``{".pdf", ".docx"}``)."""
        ...

    def extract(self, filepath: Path) -> tuple[str, float]:
        """Extract text from *filepath*.

        Returns
        -------
        tuple[str, float]
            ``(extracted_text, confidence_score)``.  A confidence of
            ``0.0`` signals failure.
        """
        ...


class ExtractionChain:
    """Configurable fallback chain of extraction backends.

    Tries backends in order for the given file.  Only backends whose
    ``supported_extensions`` include the file's suffix are attempted.

    Parameters
    ----------
    backends:
        Ordered list of extraction backends.  First successful
        extraction wins.
    """

    def __init__(self, backends: list[ExtractionBackend]) -> None:
        self._backends = list(backends)

    @property
    def backends(self) -> list[ExtractionBackend]:
        return list(self._backends)

    def extract(self, filepath: Path) -> tuple[str, float, str]:
        """Extract text from *filepath* using the first successful backend.

        Returns
        -------
        tuple[str, float, str]
            ``(text, confidence, backend_name)``.  Returns ``("", 0.0, "")``
            if no backend supports the file extension or all supported
            backends fail.
        """
        suffix = filepath.suffix.lower()
        errors: list[str] = []

        for backend in self._backends:
            if suffix not in backend.supported_extensions:
                continue
            try:
                text, confidence = backend.extract(filepath)
                if text.strip() and confidence > 0.0:
                    return text, confidence, backend.name
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{backend.name}: {exc}")
                logger.debug("Backend %s failed for %s: %s", backend.name, filepath, exc)

        if errors:
            logger.warning("All backends failed for %s: %s", filepath, "; ".join(errors))

        return "", 0.0, ""

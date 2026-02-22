"""dd_agents.extraction -- document extraction pipeline.

Converts every data-room file to a canonical markdown representation
using a fallback chain: markitdown -> pdftotext -> pytesseract -> direct read.
"""

from __future__ import annotations

from dd_agents.extraction.pipeline import ExtractionPipeline, ExtractionPipelineError

__all__ = ["ExtractionPipeline", "ExtractionPipelineError"]

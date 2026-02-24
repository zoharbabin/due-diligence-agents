"""dd_agents.extraction -- document extraction pipeline.

Converts every data-room file to a canonical markdown representation
using a multi-stage fallback chain:

    Normal PDF:  pymupdf -> pdftotext -> markitdown -> GLM-OCR -> pytesseract -> Claude vision -> direct read
    Scanned PDF: GLM-OCR -> pytesseract -> Claude vision -> direct read
    Images:      markitdown -> GLM-OCR -> pytesseract -> Claude vision -> diagram placeholder
    Office:      markitdown -> direct read
    Plain text:  direct read
"""

from __future__ import annotations

from dd_agents.extraction.pipeline import ExtractionPipeline, ExtractionPipelineError

__all__ = ["ExtractionPipeline", "ExtractionPipelineError"]

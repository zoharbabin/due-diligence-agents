"""Batch scheduling with subject complexity scoring (Issue #148).

Provides smart batch scheduling that:
1. Scores subject complexity based on file count and total document size
2. Sorts subjects simple-first for fast wins
3. Respects batch size and token limits
4. Returns ordered batches ready for parallel agent execution
"""

from __future__ import annotations

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Complexity tiers
# ---------------------------------------------------------------------------

_SIMPLE_THRESHOLD: float = 10.0
_COMPLEX_THRESHOLD: float = 50.0

# Scoring weights
_FILE_WEIGHT: float = 3.0
_SIZE_WEIGHT: float = 1.0
_SIZE_UNIT: float = 100_000.0  # 100KB


# ---------------------------------------------------------------------------
# Subject complexity model
# ---------------------------------------------------------------------------


class SubjectComplexity(BaseModel):
    """Complexity assessment for a single subject."""

    subject_safe_name: str = Field(description="Normalized subject identifier")
    file_count: int = Field(default=0, description="Number of files in subject data room folder")
    total_bytes: int = Field(default=0, description="Total byte size of all subject documents")
    score: float = Field(default=0.0, description="Composite complexity score")
    tier: str = Field(default="simple", description="Tier: simple, medium, complex")
    estimated_tokens: int = Field(default=0, description="Estimated token count for this subject's documents")


def score_subject_complexity(
    subject_safe_name: str,
    *,
    file_count: int = 0,
    total_bytes: int = 0,
) -> SubjectComplexity:
    """Score a subject's complexity based on their document profile.

    Score formula: (file_count * FILE_WEIGHT) + (total_bytes / SIZE_UNIT * SIZE_WEIGHT)

    Tiers:
    - simple: score < 10 (1-2 files, small)
    - medium: 10 <= score < 50 (3-10 files, moderate size)
    - complex: score >= 50 (10+ files, large documents)
    """
    score = (file_count * _FILE_WEIGHT) + (total_bytes / _SIZE_UNIT * _SIZE_WEIGHT)

    if score < _SIMPLE_THRESHOLD:
        tier = "simple"
    elif score < _COMPLEX_THRESHOLD:
        tier = "medium"
    else:
        tier = "complex"

    # Rough token estimate: ~4 chars per token
    estimated_tokens = total_bytes // 4

    return SubjectComplexity(
        subject_safe_name=subject_safe_name,
        file_count=file_count,
        total_bytes=total_bytes,
        score=score,
        tier=tier,
        estimated_tokens=estimated_tokens,
    )


# ---------------------------------------------------------------------------
# Batch scheduler
# ---------------------------------------------------------------------------


class BatchScheduler:
    """Schedule subjects into ordered batches for agent execution.

    Parameters
    ----------
    max_batch_size:
        Maximum number of subjects per batch.
    max_batch_tokens:
        Optional maximum estimated tokens per batch.  When set, batches
        are split when the cumulative token estimate exceeds this value.
    """

    def __init__(
        self,
        max_batch_size: int = 20,
        max_batch_tokens: int | None = None,
    ) -> None:
        self.max_batch_size = max_batch_size
        self.max_batch_tokens = max_batch_tokens

    def schedule(
        self,
        complexities: list[SubjectComplexity],
    ) -> list[list[SubjectComplexity]]:
        """Partition subjects into ordered batches.

        Subjects are sorted by complexity score ascending (simple first)
        for fast wins, then packed into batches respecting size and token limits.
        """
        if not complexities:
            return []

        sorted_subjects = sorted(complexities, key=lambda c: c.score)

        batches: list[list[SubjectComplexity]] = []
        current_batch: list[SubjectComplexity] = []
        current_tokens = 0

        for subject in sorted_subjects:
            # Check if adding this subject would exceed limits
            would_exceed_size = len(current_batch) >= self.max_batch_size
            would_exceed_tokens = (
                self.max_batch_tokens is not None
                and current_tokens + subject.estimated_tokens > self.max_batch_tokens
                and len(current_batch) > 0
            )

            if would_exceed_size or would_exceed_tokens:
                batches.append(current_batch)
                current_batch = []
                current_tokens = 0

            current_batch.append(subject)
            current_tokens += subject.estimated_tokens

        if current_batch:
            batches.append(current_batch)

        return batches

    @staticmethod
    def batch_names(batch: list[SubjectComplexity]) -> list[str]:
        """Extract subject_safe_name list from a batch."""
        return [c.subject_safe_name for c in batch]

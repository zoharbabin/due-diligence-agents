"""Batch scheduling with customer complexity scoring (Issue #148).

Provides smart batch scheduling that:
1. Scores customer complexity based on file count and total document size
2. Sorts customers simple-first for fast wins
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
# Customer complexity model
# ---------------------------------------------------------------------------


class CustomerComplexity(BaseModel):
    """Complexity assessment for a single customer."""

    customer_safe_name: str = Field(description="Normalized customer identifier")
    file_count: int = Field(default=0, description="Number of files in customer data room folder")
    total_bytes: int = Field(default=0, description="Total byte size of all customer documents")
    score: float = Field(default=0.0, description="Composite complexity score")
    tier: str = Field(default="simple", description="Tier: simple, medium, complex")
    estimated_tokens: int = Field(default=0, description="Estimated token count for this customer's documents")


def score_customer_complexity(
    customer_safe_name: str,
    *,
    file_count: int = 0,
    total_bytes: int = 0,
) -> CustomerComplexity:
    """Score a customer's complexity based on their document profile.

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

    return CustomerComplexity(
        customer_safe_name=customer_safe_name,
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
    """Schedule customers into ordered batches for agent execution.

    Parameters
    ----------
    max_batch_size:
        Maximum number of customers per batch.
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
        complexities: list[CustomerComplexity],
    ) -> list[list[CustomerComplexity]]:
        """Partition customers into ordered batches.

        Customers are sorted by complexity score ascending (simple first)
        for fast wins, then packed into batches respecting size and token limits.
        """
        if not complexities:
            return []

        sorted_customers = sorted(complexities, key=lambda c: c.score)

        batches: list[list[CustomerComplexity]] = []
        current_batch: list[CustomerComplexity] = []
        current_tokens = 0

        for customer in sorted_customers:
            # Check if adding this customer would exceed limits
            would_exceed_size = len(current_batch) >= self.max_batch_size
            would_exceed_tokens = (
                self.max_batch_tokens is not None
                and current_tokens + customer.estimated_tokens > self.max_batch_tokens
                and len(current_batch) > 0
            )

            if would_exceed_size or would_exceed_tokens:
                batches.append(current_batch)
                current_batch = []
                current_tokens = 0

            current_batch.append(customer)
            current_tokens += customer.estimated_tokens

        if current_batch:
            batches.append(current_batch)

        return batches

    @staticmethod
    def batch_names(batch: list[CustomerComplexity]) -> list[str]:
        """Extract customer_safe_name list from a batch."""
        return [c.customer_safe_name for c in batch]

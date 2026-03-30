"""report_progress MCP tool.

Allows agents to report progress back to the orchestrator for liveness
monitoring and progress tracking.
"""

from __future__ import annotations

from typing import Any


def report_progress(
    agent_name: str,
    customers_processed: int,
    total_customers: int,
    current_customer: str,
) -> dict[str, Any]:
    """Return a progress snapshot.

    Args:
        agent_name: Name of the reporting agent.
        customers_processed: Count of customers completed so far.
        total_customers: Total customers assigned to this agent.
        current_customer: Customer currently being processed.

    Returns:
        Progress dict with percentage, counts, and status.
    """
    pct = (customers_processed / total_customers * 100.0) if total_customers > 0 else 0.0

    status = "in_progress"
    if customers_processed >= total_customers:
        status = "complete"
    elif customers_processed == 0:
        status = "starting"

    return {
        "agent": agent_name,
        "customers_processed": customers_processed,
        "total_customers": total_customers,
        "current_customer": current_customer,
        "progress_pct": round(pct, 1),
        "status": status,
    }

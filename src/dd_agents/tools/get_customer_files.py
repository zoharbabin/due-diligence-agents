"""get_customer_files MCP tool.

Returns the file list and count for a given customer name from the
customers CSV inventory.
"""

from __future__ import annotations

from typing import Any


def get_customer_files(
    customer_name: str,
    customers_csv: list[dict[str, Any]],
) -> dict[str, Any]:
    """Return file list and count for *customer_name*.

    Looks up the customer by ``customer_safe_name`` in *customers_csv*.

    Args:
        customer_name: The ``customer_safe_name`` to look up.
        customers_csv: List of customer dicts, each with at least
            ``customer_safe_name`` and ``file_list`` keys.

    Returns:
        ``{"customer": str, "file_count": int, "files": list[str]}`` or
        ``{"error": "unknown_customer", "name": str}``.
    """
    for row in customers_csv:
        safe_name = row.get("customer_safe_name", "")
        if safe_name == customer_name:
            file_list = row.get("file_list", [])
            if isinstance(file_list, str):
                # Handle comma-separated string
                file_list = [f.strip() for f in file_list.split(",") if f.strip()]
            return {
                "customer": safe_name,
                "file_count": len(file_list),
                "files": file_list,
            }

    return {
        "error": "unknown_customer",
        "name": customer_name,
    }

"""Contract date reconciliation.

Reconciles database contract end-dates against data-room evidence and
classifies customers into one of five statuses.  Runs when
``source_of_truth.customer_database`` exists in ``deal-config.json``.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Any

from dd_agents.models.reporting import (
    ContractDateReconciliation,
    ContractDateReconciliationEntry,
)

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

# The five classification statuses
STATUS_ACTIVE_DB_STALE = "Active-Database Stale"
STATUS_ACTIVE_AUTO_RENEWAL = "Active-Auto-Renewal"
STATUS_LIKELY_ACTIVE = "Likely Active-Needs Confirmation"
STATUS_EXPIRED_CONFIRMED = "Expired-Confirmed"
STATUS_EXPIRED_NO_CONTRACTS = "Expired-No Contracts"


class ContractDateReconciler:
    """Classify customers by contract status using database + data room evidence."""

    def __init__(self, reference_date: date | None = None) -> None:
        """
        Parameters
        ----------
        reference_date:
            The date to treat as "today" for expiry comparison.  Defaults to
            the actual current UTC date.
        """
        self._today = reference_date or date.today()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def reconcile(
        self,
        customer_database: list[dict[str, Any]],
        findings: dict[str, list[dict[str, Any]]],
        customers: list[str] | None = None,
        run_id: str = "",
    ) -> ContractDateReconciliation:
        """Run the reconciliation protocol.

        Parameters
        ----------
        customer_database:
            Rows from the customer database.  Each dict should have at minimum
            ``customer``, ``contract_end_date`` (YYYY-MM-DD), and ``arr``
            (numeric).
        findings:
            ``{customer_name: [finding_dicts]}`` -- keyed by canonical
            customer name (not safe_name).  Used to look for renewal
            evidence such as auto-renewal clauses, POs, etc.
        customers:
            Optional explicit customer list.  When not supplied, all entries
            in *customer_database* are processed.
        run_id:
            Current pipeline run identifier.
        """
        entries: list[ContractDateReconciliationEntry] = []

        for db_row in customer_database:
            customer_name = db_row.get("customer", "")
            if customers and customer_name not in customers:
                continue

            end_date_str = db_row.get("contract_end_date", "")
            arr = float(db_row.get("arr", 0))

            entry = self._classify(
                customer_name=customer_name,
                end_date_str=end_date_str,
                arr=arr,
                customer_findings=findings.get(customer_name, []),
                db_row=db_row,
            )
            entries.append(entry)

        total_reclassified = sum(e.arr for e in entries if "active" in e.status.lower())
        total_expired = sum(e.arr for e in entries if "expired" in e.status.lower())

        return ContractDateReconciliation(
            run_id=run_id or "unknown",
            generated_at=datetime.now(UTC).isoformat(),
            entries=entries,
            total_reclassified_arr=total_reclassified,
            total_expired_arr=total_expired,
        )

    def write_reconciliation(
        self,
        result: ContractDateReconciliation,
        output_path: Path,
    ) -> None:
        """Serialize reconciliation result to JSON."""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(result.model_dump_json(indent=2))

    # ------------------------------------------------------------------
    # Classification logic
    # ------------------------------------------------------------------

    def _classify(
        self,
        customer_name: str,
        end_date_str: str,
        arr: float,
        customer_findings: list[dict[str, Any]],
        db_row: dict[str, Any],
    ) -> ContractDateReconciliationEntry:
        """Classify a single customer into one of the five statuses."""
        # Parse end date
        end_date = self._parse_date(end_date_str)

        # No contract documents at all?
        has_contracts = bool(customer_findings)

        if end_date is None:
            # Cannot determine expiry
            if not has_contracts:
                return ContractDateReconciliationEntry(
                    customer=customer_name,
                    database_end_date=end_date_str,
                    actual_end_date="",
                    arr=arr,
                    status=STATUS_EXPIRED_NO_CONTRACTS,
                    evidence="No contract documents found in data room",
                    evidence_file="",
                )
            return ContractDateReconciliationEntry(
                customer=customer_name,
                database_end_date=end_date_str,
                actual_end_date="",
                arr=arr,
                status=STATUS_LIKELY_ACTIVE,
                evidence="Contract end date could not be parsed; contracts exist in data room",
                evidence_file="",
            )

        contract_expired = end_date < self._today

        if not contract_expired:
            # Database says still active -- no reconciliation needed
            return ContractDateReconciliationEntry(
                customer=customer_name,
                database_end_date=end_date_str,
                actual_end_date=end_date_str,
                arr=arr,
                status=STATUS_ACTIVE_DB_STALE,
                evidence="Database end date is in the future; contract is active",
                evidence_file="",
            )

        # Contract is database-expired -- check for renewal evidence
        if not has_contracts:
            return ContractDateReconciliationEntry(
                customer=customer_name,
                database_end_date=end_date_str,
                actual_end_date="",
                arr=arr,
                status=STATUS_EXPIRED_NO_CONTRACTS,
                evidence="Database shows expired and no contract documents found",
                evidence_file="",
            )

        # Look for auto-renewal signals in findings
        has_auto_renewal = self._has_auto_renewal_evidence(customer_findings)
        has_renewal_evidence = self._has_renewal_evidence(customer_findings)

        if has_auto_renewal:
            return ContractDateReconciliationEntry(
                customer=customer_name,
                database_end_date=end_date_str,
                actual_end_date="",
                arr=arr,
                status=STATUS_ACTIVE_AUTO_RENEWAL,
                evidence="Auto-renewal clause found in contract documents",
                evidence_file=self._get_evidence_file(customer_findings),
            )

        if has_renewal_evidence:
            return ContractDateReconciliationEntry(
                customer=customer_name,
                database_end_date=end_date_str,
                actual_end_date="",
                arr=arr,
                status=STATUS_ACTIVE_DB_STALE,
                evidence="Renewal evidence found (order form, PO, or amendment post-expiry)",
                evidence_file=self._get_evidence_file(customer_findings),
            )

        if arr > 0:
            return ContractDateReconciliationEntry(
                customer=customer_name,
                database_end_date=end_date_str,
                actual_end_date="",
                arr=arr,
                status=STATUS_LIKELY_ACTIVE,
                evidence="Database expired but ARR > 0; needs confirmation",
                evidence_file="",
            )

        return ContractDateReconciliationEntry(
            customer=customer_name,
            database_end_date=end_date_str,
            actual_end_date=end_date_str,
            arr=arr,
            status=STATUS_EXPIRED_CONFIRMED,
            evidence="Contract expired per database; no renewal evidence found",
            evidence_file="",
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_date(date_str: str) -> date | None:
        """Parse an ISO-8601 date string (YYYY-MM-DD)."""
        if not date_str:
            return None
        try:
            return datetime.strptime(date_str[:10], "%Y-%m-%d").date()
        except (ValueError, TypeError):
            logger.debug("Could not parse date %r", date_str)
            return None

    @staticmethod
    def _has_auto_renewal_evidence(findings: list[dict[str, Any]]) -> bool:
        """Check if any finding mentions auto-renewal."""
        keywords = ("auto-renewal", "auto renewal", "automatic renewal", "evergreen")
        for f in findings:
            text = (f.get("title", "") + " " + f.get("description", "") + " " + f.get("category", "")).lower()
            if any(kw in text for kw in keywords):
                return True
        return False

    @staticmethod
    def _has_renewal_evidence(findings: list[dict[str, Any]]) -> bool:
        """Check if any finding indicates renewal activity."""
        keywords = ("renewal", "renewed", "order form", "purchase order", "amendment")
        for f in findings:
            text = (f.get("title", "") + " " + f.get("description", "")).lower()
            if any(kw in text for kw in keywords):
                return True
        return False

    @staticmethod
    def _get_evidence_file(findings: list[dict[str, Any]]) -> str:
        """Return the first citation source_path from findings, if any."""
        for f in findings:
            cits = f.get("citations", [])
            if cits:
                cit = cits[0]
                if isinstance(cit, dict):
                    sp: str = cit.get("source_path", "")
                    if sp:
                        return sp
        return ""

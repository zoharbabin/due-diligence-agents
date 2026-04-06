"""Reference file classifier and agent router.

Reference files are files NOT under a customer directory.  They are classified
by category based on filename/path patterns and routed to the appropriate
specialist agents.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path, PurePosixPath

from dd_agents.models.enums import ReferenceFileCategory
from dd_agents.models.inventory import FileEntry, ReferenceFile
from dd_agents.utils.constants import (
    AGENT_ACQUIRER_INTELLIGENCE,
    AGENT_COMMERCIAL,
    AGENT_FINANCE,
    AGENT_LEGAL,
    AGENT_PRODUCTTECH,
    ALL_SPECIALIST_AGENTS,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Classification patterns: regex on lowercased filename/path
# ---------------------------------------------------------------------------

_CATEGORY_PATTERNS: list[tuple[str, ReferenceFileCategory, str]] = [
    # Buyer Context — checked first so _buyer/ dir files are never misclassified
    (
        r"(_buyer|_acquirer|buyer.?context|10-k|annual.?report|earnings.?call|investor.?presentation)",
        ReferenceFileCategory.BUYER_CONTEXT,
        "Buyer context and strategy document",
    ),
    # DD Output / Buyer Work Product — checked second so files in "internal analysis"
    # or "readout deck" dirs are excluded even when filenames match other categories
    (
        r"(readout|dd.?report|dd.?deck|dd.?draft|internal.?analysis|work.?product|synergy.?model)",
        ReferenceFileCategory.DD_OUTPUT,
        "DD output or buyer work product (excluded from specialist analysis)",
    ),
    # Financial
    (
        r"(financ|revenue|arr|mrr|bookings|billing|invoice|p&l|profit.?loss|balance.?sheet|cash.?flow)",
        ReferenceFileCategory.FINANCIAL,
        "Financial statement or revenue data",
    ),
    # Pricing
    (r"(pric|rate.?card|discount|sku|tariff)", ReferenceFileCategory.PRICING, "Pricing or rate information"),
    # Corporate / Legal
    (
        r"(corporate|legal|governance|board|minutes|bylaws|charter|incorporat|certificate|resolut)",
        ReferenceFileCategory.CORPORATE_LEGAL,
        "Corporate governance or legal document",
    ),
    # Operational
    (
        r"(operat|process|sop|workflow|infrastructure|architecture|deploy|sla)",
        ReferenceFileCategory.OPERATIONAL,
        "Operational process or SLA",
    ),
    # Sales
    (
        r"(sales|pipeline|crm|forecast|quota|commission|territory)",
        ReferenceFileCategory.SALES,
        "Sales pipeline or CRM data",
    ),
    # Compliance
    (
        r"(complian|audit|soc|iso|gdpr|hipaa|pci|regulat|certif)",
        ReferenceFileCategory.COMPLIANCE,
        "Compliance or audit report",
    ),
    # HR
    (
        r"(employee|headcount|hr|human.?resource|payroll|benefit|compensation|org.?chart)",
        ReferenceFileCategory.HR,
        "Human resources or employee data",
    ),
]

# ---------------------------------------------------------------------------
# Agent routing table: category -> list of agents
# ---------------------------------------------------------------------------

_ROUTING_TABLE: dict[ReferenceFileCategory, list[str]] = {
    ReferenceFileCategory.FINANCIAL: [AGENT_FINANCE, AGENT_COMMERCIAL],
    ReferenceFileCategory.PRICING: [AGENT_FINANCE, AGENT_COMMERCIAL],
    ReferenceFileCategory.CORPORATE_LEGAL: [AGENT_LEGAL],
    ReferenceFileCategory.OPERATIONAL: [AGENT_PRODUCTTECH],
    ReferenceFileCategory.SALES: [AGENT_COMMERCIAL, AGENT_FINANCE],
    ReferenceFileCategory.COMPLIANCE: [AGENT_LEGAL, AGENT_PRODUCTTECH],
    ReferenceFileCategory.HR: [AGENT_FINANCE, AGENT_LEGAL],
    ReferenceFileCategory.BUYER_CONTEXT: [AGENT_ACQUIRER_INTELLIGENCE],
    ReferenceFileCategory.DD_OUTPUT: [],
    ReferenceFileCategory.OTHER: list(ALL_SPECIALIST_AGENTS),
}


class ReferenceFileClassifier:
    """Identifies and classifies non-customer (reference) files."""

    def classify(
        self,
        files: list[FileEntry],
        customer_dirs: list[str],
    ) -> list[ReferenceFile]:
        """Identify reference files and classify each by category.

        Parameters
        ----------
        files:
            All discovered files in the data room.
        customer_dirs:
            List of customer directory prefixes (e.g. ``["GroupA/Acme", "GroupA/Globex"]``).

        Returns
        -------
        list[ReferenceFile]
            Classified reference files with routing assignments.
        """
        customer_prefixes = [d.rstrip("/") + "/" for d in customer_dirs]
        ref_files: list[ReferenceFile] = []

        for entry in files:
            # Check if file is under any customer directory
            is_customer_file = any(entry.path.startswith(prefix) for prefix in customer_prefixes)
            if is_customer_file:
                continue

            category, subcategory, description = self._classify_single(entry.path)
            agents = self.route_to_agents(category)

            # DD output / buyer work products are not routed to any agent
            if not agents:
                logger.debug("Skipping DD output file: %s", entry.path)
                continue

            ref_file = ReferenceFile(
                file_path=entry.path,
                text_path=entry.text_path,
                category=category.value,
                subcategory=subcategory,
                description=description,
                assigned_to_agents=agents,
            )
            ref_files.append(ref_file)

        ref_files.sort(key=lambda r: r.file_path)
        logger.info("Classified %d reference files", len(ref_files))
        return ref_files

    def route_to_agents(self, category: ReferenceFileCategory | str) -> list[str]:
        """Determine which specialist agents should receive a reference file.

        Parameters
        ----------
        category:
            The reference file category (string or enum value).

        Returns
        -------
        list[str]
            Agent names that should receive this file.
        """
        if isinstance(category, str):
            try:
                category = ReferenceFileCategory(category)
            except ValueError:
                return list(ALL_SPECIALIST_AGENTS)
        return list(_ROUTING_TABLE.get(category, ALL_SPECIALIST_AGENTS))

    def write_json(self, ref_files: list[ReferenceFile], output_path: Path) -> None:
        """Write reference files to ``reference_files.json``.

        Parameters
        ----------
        ref_files:
            Classified reference files.
        output_path:
            Destination file path.
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        data = [rf.model_dump() for rf in ref_files]
        output_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        logger.debug("Wrote reference_files.json with %d entries", len(ref_files))

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _classify_single(self, file_path: str) -> tuple[ReferenceFileCategory, str, str]:
        """Classify a single file by matching its path against known patterns."""
        lower_path = file_path.lower()
        filename = PurePosixPath(file_path).name.lower()

        for pattern, category, desc in _CATEGORY_PATTERNS:
            if re.search(pattern, lower_path, re.IGNORECASE):
                subcategory = _derive_subcategory(filename, category)
                return category, subcategory, desc

        return (
            ReferenceFileCategory.OTHER,
            "unclassified",
            "Reference file with no matching category pattern",
        )


def _derive_subcategory(filename: str, category: ReferenceFileCategory) -> str:
    """Derive a finer subcategory from the filename."""
    stem = PurePosixPath(filename).stem.lower()

    # Simple heuristic: use first meaningful word
    words = re.findall(r"[a-z]+", stem)
    if words:
        return "_".join(words[:2])
    return "general"

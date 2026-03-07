"""Synthetic data room generator for deterministic E2E and integration testing.

Generates a realistic data room with planted findings so tests can assert
on expected contract clauses without requiring real documents.
"""

from __future__ import annotations

import random
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

CUSTOMER_POOL: list[str] = [
    "Alpha Corp",
    "Beta Inc",
    "Gamma LLC",
    "Delta Partners",
    "Epsilon Group",
    "Zeta Holdings",
    "Eta Systems",
    "Theta Solutions",
    "Iota Networks",
    "Kappa Digital",
]

DOCUMENT_TYPES: list[str] = ["MSA", "NDA", "SOW", "License Agreement", "Amendment"]

_GROUP_NAMES: list[str] = ["GroupA", "GroupB"]


def _safe_filename(name: str) -> str:
    """Convert a customer name to a filesystem-safe lowercase slug."""
    return name.lower().replace(" ", "_").replace(",", "").replace(".", "")


class SyntheticDataRoomGenerator:
    """Generate a deterministic synthetic data room with planted findings.

    Parameters
    ----------
    seed:
        Random seed for reproducible output. Same seed always produces
        identical data rooms.
    """

    def __init__(self, seed: int = 42) -> None:
        self._seed = seed
        self._rng = random.Random(seed)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate(self, root: Path, num_customers: int = 5) -> Path:
        """Create a synthetic data room under *root*.

        Parameters
        ----------
        root:
            Directory in which the ``data_room/`` folder will be created.
        num_customers:
            Number of customers to generate (1-10).

        Returns
        -------
        Path
            The ``data_room/`` directory that was created.
        """
        if num_customers < 1 or num_customers > len(CUSTOMER_POOL):
            msg = f"num_customers must be between 1 and {len(CUSTOMER_POOL)}"
            raise ValueError(msg)

        data_room = root / "data_room"
        data_room.mkdir(parents=True, exist_ok=True)

        # Pick customers deterministically
        pool = list(CUSTOMER_POOL)
        self._rng.shuffle(pool)
        customers = pool[:num_customers]

        # Split customers across two groups
        mid = len(customers) // 2 or 1
        groups: dict[str, list[str]] = {
            _GROUP_NAMES[0]: customers[:mid],
            _GROUP_NAMES[1]: customers[mid:],
        }

        for group_name, group_customers in groups.items():
            for customer in group_customers:
                self._generate_customer(data_room / group_name / customer, customer)

        self._generate_reference(data_room / "_reference")

        return data_room

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _generate_customer(self, customer_dir: Path, customer_name: str) -> None:
        """Generate 2-4 markdown documents for a single customer."""
        customer_dir.mkdir(parents=True, exist_ok=True)

        num_docs = self._rng.randint(2, 4)
        doc_types = list(DOCUMENT_TYPES)
        self._rng.shuffle(doc_types)
        selected_types = doc_types[:num_docs]

        slug = _safe_filename(customer_name)

        for doc_type in selected_types:
            filename = f"{doc_type.lower().replace(' ', '_')}_{slug}.pdf.md"
            content = self._render_document(customer_name, doc_type)
            (customer_dir / filename).write_text(content, encoding="utf-8")

    def _render_document(self, customer_name: str, doc_type: str) -> str:
        """Render a single synthetic contract document as markdown."""
        year = self._rng.randint(2021, 2025)
        month = self._rng.randint(1, 12)
        day = self._rng.randint(1, 28)
        effective_date = f"{year}-{month:02d}-{day:02d}"
        term_months = self._rng.choice([12, 24, 36, 48])
        annual_value = self._rng.randint(50, 500) * 1000

        sections: list[str] = [
            f"# {doc_type} - {customer_name}\n",
            f"Effective Date: {effective_date}\nTerm: {term_months} months\nAnnual Value: ${annual_value:,}\n",
        ]

        # Every document gets a change of control clause
        sections.append(
            "## Clause 5.3 - Change of Control\n"
            "In the event of a change of control of either party, including but not limited "
            "to merger, acquisition, or sale of substantially all assets, the non-affected "
            "party shall have the right to terminate this agreement upon 30 days written notice.\n"
        )

        # Every document gets a liability cap
        liability_cap = self._rng.randint(100, 2000) * 1000
        sections.append(
            "## Clause 8.1 - Limitation of Liability\n"
            f"The total aggregate liability of either party shall not exceed ${liability_cap:,} "
            "under any circumstances, excluding cases of gross negligence or willful misconduct.\n"
        )

        # Every document gets auto-renewal terms
        renewal_months = self._rng.choice([6, 12, 24])
        notice_days = self._rng.choice([30, 60, 90])
        sections.append(
            "## Clause 9.2 - Auto-Renewal\n"
            f"This agreement shall automatically renew for successive {renewal_months}-month "
            f"periods unless either party provides at least {notice_days} days prior written "
            "notice of non-renewal before the end of the then-current term.\n"
        )

        # IP ownership clause on MSA / License Agreement / SOW
        if doc_type in {"MSA", "License Agreement", "SOW"}:
            sections.append(
                "## Clause 11.1 - Intellectual Property Ownership\n"
                "All intellectual property rights in any deliverables created under this "
                "agreement shall vest in the commissioning party upon full payment, unless "
                "otherwise specified in an applicable statement of work.\n"
            )

        # Termination for convenience on some documents (deterministic per doc)
        if self._rng.random() < 0.6:
            tfic_days = self._rng.choice([30, 60, 90])
            sections.append(
                "## Clause 12.4 - Termination for Convenience\n"
                f"Either party may terminate this agreement for any reason upon {tfic_days} "
                "days prior written notice to the other party. Upon such termination, "
                "all fees for services rendered through the termination date shall remain due.\n"
            )

        return "\n".join(sections)

    def _generate_reference(self, ref_dir: Path) -> None:
        """Create the _reference/ folder with a buyer overview."""
        ref_dir.mkdir(parents=True, exist_ok=True)
        (ref_dir / "buyer_overview.md").write_text(
            "# Buyer Company Overview\n\n"
            "Company: Meridian Holdings\n"
            "Industry: Enterprise SaaS\n"
            "Revenue: $500M ARR\n"
            "Headquarters: Generic City, ST\n",
            encoding="utf-8",
        )

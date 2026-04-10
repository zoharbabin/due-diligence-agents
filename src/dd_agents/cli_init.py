"""Init command logic: scan data room, build config, prompt user, write deal-config.json."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from rich.panel import Panel

if TYPE_CHECKING:
    from rich.console import Console

DEFAULT_FOCUS_AREAS = [
    "change_of_control_clauses",
    "ip_ownership",
    "revenue_recognition",
    "customer_concentration",
    "auto_renewal_terms",
    "data_privacy_compliance",
    "liability_caps",
    "non_compete_agreements",
]

# Human-readable labels for focus areas (displayed in interactive mode).
_FOCUS_AREA_LABELS: dict[str, str] = {
    "change_of_control_clauses": "Change of control clauses",
    "ip_ownership": "IP ownership",
    "revenue_recognition": "Revenue recognition",
    "customer_concentration": "Customer concentration",
    "auto_renewal_terms": "Auto-renewal terms",
    "data_privacy_compliance": "Data privacy compliance",
    "liability_caps": "Liability caps",
    "non_compete_agreements": "Non-compete agreements",
    "contract_assignability": "Contract assignability (asset sale)",
    "purchased_assets_schedule": "Purchased assets schedule completeness",
    "excluded_liabilities": "Excluded vs. assumed liabilities",
    "employee_transfer": "Employee transfer / key-person risk",
    "cure_costs": "Cure costs for defaulted contracts",
}

VALID_DEAL_TYPES = [
    "acquisition",
    "asset_sale",
    "merger",
    "divestiture",
    "investment",
    "joint_venture",
    "other",
]


def scan_data_room(path: Path) -> dict[str, Any]:
    """Scan a data room directory using FileDiscovery and SubjectRegistryBuilder.

    Returns a dict with keys: groups, subjects, subject_names, file_count, counts.
    """
    from dd_agents.inventory.discovery import FileDiscovery
    from dd_agents.inventory.subjects import SubjectRegistryBuilder

    discovery = FileDiscovery()
    files = discovery.discover(path)

    builder = SubjectRegistryBuilder()
    subjects, counts = builder.build(path, files)

    groups = sorted({c.group for c in subjects})
    subject_names = [c.name for c in subjects]

    return {
        "groups": groups,
        "subjects": subjects,
        "subject_names": subject_names,
        "file_count": counts.total_files,
        "counts": counts,
    }


def prompt_deal_type(console: Console) -> str:
    """Interactive deal type prompt with validation and re-prompting."""
    labels = ", ".join(VALID_DEAL_TYPES)
    while True:
        raw = input(f"Deal type ({labels}) [acquisition]: ").strip().lower()
        if not raw:
            return "acquisition"
        if raw in VALID_DEAL_TYPES:
            return raw
        console.print(f"[bold yellow]Invalid deal type:[/bold yellow] '{raw}'")
        console.print(f"  Choose one of: {labels}\n")


def build_config_dict(
    *,
    buyer: str,
    target: str,
    deal_type: str,
    focus_areas: list[str],
    name_variants: list[str] | None = None,
    scan_result: dict[str, Any] | None = None,
    data_room_path: str | None = None,
) -> dict[str, Any]:
    """Assemble a deal-config dict from user inputs and scan results."""
    config: dict[str, Any] = {
        "config_version": "1.0.0",
        "buyer": {"name": buyer},
        "target": {"name": target},
        "deal": {
            "type": deal_type,
            "focus_areas": focus_areas,
        },
    }

    if name_variants:
        config["target"]["entity_name_variants_for_contract_matching"] = name_variants

    # Seed entity_aliases from detected subject folders names
    canonical_to_variants: dict[str, list[str]] = {}
    if scan_result and scan_result.get("subjects"):
        for subject_entry in scan_result["subjects"]:
            # Use folder name as canonical; add underscore-replaced variant if different
            folder_name: str = subject_entry.name
            clean_name = folder_name.replace("_", " ")
            if clean_name != folder_name:
                canonical_to_variants[clean_name] = [folder_name]

    if canonical_to_variants:
        config["entity_aliases"] = {
            "canonical_to_variants": canonical_to_variants,
        }

    if data_room_path:
        config["data_room"] = {"path": data_room_path}

    return config


def prompt_focus_areas(console: Console) -> list[str]:
    """Interactive numbered multi-select for focus areas."""
    console.print("\nWhat should the analysis focus on?")
    for i, area in enumerate(DEFAULT_FOCUS_AREAS, 1):
        label = _FOCUS_AREA_LABELS.get(area, area)
        console.print(f"  {i}. {label}")
    console.print(f"  {len(DEFAULT_FOCUS_AREAS) + 1}. (add custom)")

    default_indices = "1,2,3,4"
    raw = input(f"Select focus areas (comma-separated numbers) [{default_indices}]: ").strip()
    if not raw:
        raw = default_indices

    selected: list[str] = []
    for token in raw.split(","):
        token = token.strip()
        if not token:
            continue
        try:
            idx = int(token)
        except ValueError:
            continue
        if 1 <= idx <= len(DEFAULT_FOCUS_AREAS):
            area = DEFAULT_FOCUS_AREAS[idx - 1]
            if area not in selected:
                selected.append(area)
        elif idx == len(DEFAULT_FOCUS_AREAS) + 1:
            custom = input("Enter custom focus area name: ").strip()
            if custom and custom not in selected:
                selected.append(custom)

    return selected if selected else DEFAULT_FOCUS_AREAS[:4]


def print_scan_summary(console: Console, scan_result: dict[str, Any]) -> None:
    """Print a Rich panel summarising the data room scan."""
    groups = scan_result.get("groups", [])
    subject_names = scan_result.get("subject_names", [])
    file_count = scan_result.get("file_count", 0)

    n_groups = len(groups)
    n_subjects = len(subject_names)

    lines = [f"Found {n_groups} group(s), {n_subjects} subject(s), {file_count} file(s)"]
    if groups:
        lines.append(f"Groups: {', '.join(groups)}")
    if subject_names:
        display_names = subject_names[:10]
        suffix = f", ... (+{n_subjects - 10} more)" if n_subjects > 10 else ""
        lines.append(f"Subjects: {', '.join(display_names)}{suffix}")

    if n_subjects == 0:
        lines.append("")
        lines.append("Tip: No subjects detected. The data room should be organized as:")
        lines.append("  data_room/GroupName/SubjectName/files...")
        lines.append("Example: data_room/NorthAmerica/Acme_Corp/contract.pdf")

    console.print(Panel("\n".join(lines), title="Data Room Scan", border_style="cyan"))


def write_config(
    config_dict: dict[str, Any],
    output_path: Path,
    console: Console,
    err_console: Console,
    force: bool = False,
    non_interactive: bool = False,
) -> bool:
    """Validate and write config dict to a JSON file.

    Returns True on success, False on failure.
    """
    from dd_agents.config import ConfigValidationError, validate_deal_config

    # Validate
    try:
        validate_deal_config(config_dict)
    except ConfigValidationError as exc:
        err_console.print(
            Panel(
                f"[bold red]Validation Error:[/bold red] {exc}",
                title="Error",
                border_style="red",
            )
        )
        return False

    # Check overwrite
    output_path = Path(output_path)
    if output_path.exists() and not force:
        if non_interactive:
            err_console.print(
                Panel(
                    f"[bold red]File exists:[/bold red] {output_path}\n"
                    "Use --force to overwrite in non-interactive mode.",
                    title="Error",
                    border_style="red",
                )
            )
            return False
        overwrite = input(f"{output_path} already exists. Overwrite? [y/N]: ").strip().lower()
        if overwrite not in ("y", "yes"):
            console.print("Aborted.")
            return False

    # Write
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(config_dict, indent=2) + "\n", encoding="utf-8")

    console.print(
        Panel(
            f"Config written to {output_path}\n"
            "\nNext steps:\n"
            f"  1. Review: {output_path}\n"
            f"  2. dd-agents validate {output_path}\n"
            f"  3. dd-agents run {output_path} --dry-run\n"
            f"  4. dd-agents run {output_path}",
            title="Success",
            border_style="green",
        )
    )
    return True

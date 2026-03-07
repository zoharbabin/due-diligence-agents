"""Click CLI entry point for the dd-agents pipeline.

Registered as ``dd-agents`` console script via pyproject.toml.
"""

from __future__ import annotations

import asyncio
import json
import logging
import traceback
from pathlib import Path
from typing import Any

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

import dd_agents
from dd_agents.config import (
    ConfigFileNotFoundError,
    ConfigParseError,
    ConfigValidationError,
    load_deal_config,
)

console = Console()
err_console = Console(stderr=True)


# ---------------------------------------------------------------------------
# Click group
# ---------------------------------------------------------------------------


@click.group()
@click.version_option(version=dd_agents.__version__, prog_name="dd-agents")
def main() -> None:
    """Due Diligence Agents -- forensic M&A due diligence pipeline."""


# ---------------------------------------------------------------------------
# run command
# ---------------------------------------------------------------------------


@main.command()
@click.argument(
    "config_path",
    type=click.Path(exists=False, dir_okay=False, path_type=Path),
)
@click.option(
    "--mode",
    type=click.Choice(["full", "incremental"], case_sensitive=False),
    default=None,
    help="Override execution mode from the config file.",
)
@click.option(
    "--verbose",
    "-v",
    is_flag=True,
    default=False,
    help="Enable verbose logging output.",
)
@click.option(
    "--resume-from",
    "resume_from",
    type=int,
    default=0,
    help="Resume pipeline from a specific step number (1-35).",
)
@click.option(
    "--dry-run",
    "dry_run",
    is_flag=True,
    default=False,
    help="Validate config and print what would run without executing.",
)
@click.option(
    "--quick-scan",
    "quick_scan",
    is_flag=True,
    default=False,
    help="Run a quick Red Flag scan only (steps 1-13 + Red Flag Scanner agent).",
)
@click.option(
    "--model-profile",
    "model_profile",
    type=click.Choice(["economy", "standard", "premium"], case_sensitive=False),
    default=None,
    help="Override model profile: economy (Haiku), standard (Sonnet), premium (Opus).",
)
@click.option(
    "--model-override",
    "model_overrides",
    multiple=True,
    help="Per-agent model override in agent=model format (e.g. --model-override legal=claude-opus-4-6).",
)
def run(
    config_path: Path,
    mode: str | None,
    verbose: bool,
    resume_from: int,
    dry_run: bool,
    quick_scan: bool,
    model_profile: str | None,
    model_overrides: tuple[str, ...],
) -> None:
    """Run the due diligence pipeline with a deal-config.json file."""
    if verbose:
        logging.basicConfig(level=logging.WARNING, format="%(name)s: %(message)s")
        logging.getLogger("dd_agents").setLevel(logging.DEBUG)
        logging.getLogger("claude_agent_sdk").setLevel(logging.WARNING)
        logging.getLogger("asyncio").setLevel(logging.WARNING)

    # --- Load and validate config ---
    try:
        deal_config = load_deal_config(config_path)
    except ConfigFileNotFoundError as exc:
        _print_error("Config Error", str(exc))
        raise SystemExit(1) from exc
    except ConfigParseError as exc:
        _print_error("JSON Error", str(exc))
        raise SystemExit(1) from exc
    except ConfigValidationError as exc:
        _print_error("Validation Error", str(exc))
        err_console.print()
        _print_validation_errors(exc)
        raise SystemExit(1) from exc

    # Apply mode override if provided
    if mode is not None:
        from dd_agents.models.enums import ExecutionMode

        deal_config.execution.execution_mode = ExecutionMode(mode)

    # Apply model profile/override if provided (Issue #146)
    if model_profile is not None:
        deal_config.agent_models.profile = model_profile
    if model_overrides:
        for override in model_overrides:
            if "=" in override:
                agent_name, model_id = override.split("=", 1)
                deal_config.agent_models.overrides[agent_name.strip()] = model_id.strip()

    _print_config_summary(deal_config)

    # --- Validate resume-from ---
    if resume_from < 0 or resume_from > 35:
        _print_error("Invalid Option", f"--resume-from must be 0-35, got {resume_from}")
        raise SystemExit(1)

    # --- Dry run ---
    if dry_run:
        console.print()
        _print_dry_run(deal_config, resume_from)
        return

    # --- Resolve project directory ---
    data_room_cfg = deal_config.model_extra.get("data_room") if deal_config.model_extra else None
    data_room_path_str: str = data_room_cfg.get("path", "") if isinstance(data_room_cfg, dict) else ""
    project_dir = Path(data_room_path_str).resolve() if data_room_path_str else config_path.resolve().parent

    if not project_dir.is_dir():
        _print_error(
            "Data Room Error",
            f"Data room directory does not exist: {project_dir}",
        )
        raise SystemExit(1)

    # --- Run pipeline ---
    from dd_agents.orchestrator.engine import BlockingGateError, PipelineEngine

    engine = PipelineEngine(
        project_dir=project_dir,
        deal_config_path=config_path.resolve(),
    )

    # Pass CLI overrides through options dict so step 1 can apply them
    # after loading the raw config file.
    run_options: dict[str, Any] = {}
    if mode is not None:
        run_options["execution_mode"] = mode
    if quick_scan:
        run_options["quick_scan"] = True

    console.print()
    console.print(
        Panel(
            f"[bold green]Starting pipeline[/bold green]\n"
            f"Project: {project_dir}\n"
            f"Mode: {deal_config.execution.execution_mode.value}\n"
            f"Resume from: {'step ' + str(resume_from) if resume_from else 'beginning'}",
            title="Pipeline",
            border_style="green",
        )
    )

    try:
        state = asyncio.run(engine.run(resume_from_step=resume_from, options=run_options))

        # Print completion summary
        console.print()
        completed = len(state.completed_steps)
        errors = len(state.errors)
        total_cost = sum(state.agent_costs.values())

        summary_parts = [
            "[bold green]Pipeline completed[/bold green]",
            f"Run ID: {state.run_id}",
            f"Steps completed: {completed}/35",
        ]

        if errors:
            summary_parts.append(f"Errors: {errors}")
        if total_cost > 0:
            summary_parts.append(f"Total cost: ${total_cost:.4f}")
        if state.audit_passed:
            summary_parts.append("Audit: [bold green]PASSED[/bold green]")
        elif state.validation_results:
            summary_parts.append("Audit: [bold yellow]INCOMPLETE[/bold yellow]")

        # List key output files so the user can click to open them.
        run_dir = state.run_dir
        key_files: list[tuple[str, Path]] = [
            ("Excel Report", run_dir / "report" / "dd_report.xlsx"),
            ("HTML Report", run_dir / "report" / "dd_report.html"),
            ("Audit Report", run_dir / "audit.json"),
            ("DoD Results", run_dir / "dod_results.json"),
            ("Numerical Manifest", run_dir / "numerical_manifest.json"),
            ("Findings", run_dir / "findings" / "merged"),
        ]
        existing = [(label, p) for label, p in key_files if p.exists()]
        if existing:
            summary_parts.append("")
            summary_parts.append("[bold]Key outputs:[/bold]")
            for label, p in existing:
                summary_parts.append(f"  {label}: [link=file://{p}]{p}[/link]")

        console.print(
            Panel(
                "\n".join(summary_parts),
                title="Complete",
                border_style="green",
            )
        )

    except BlockingGateError as exc:
        console.print()
        _print_error(
            "Blocking Gate Failed",
            str(exc),
            extra_lines=[
                f"Step: {engine.state.current_step.value}",
                "The pipeline cannot continue past this blocking gate.",
                "",
                "To resume from a specific step after fixing the issue:",
                f"  dd-agents run {config_path} --resume-from {engine.state.current_step.step_number}",
            ],
        )
        raise SystemExit(2) from exc

    except KeyboardInterrupt:
        console.print()
        console.print(
            Panel(
                "[bold yellow]Pipeline interrupted by user[/bold yellow]\n"
                f"Last completed step: {engine.state.current_step.value}\n"
                "\nTo resume:\n"
                f"  dd-agents run {config_path} --resume-from {engine.state.current_step.step_number}",
                title="Interrupted",
                border_style="yellow",
            )
        )
        raise SystemExit(130) from None

    except Exception as exc:
        console.print()
        _print_error(
            "Pipeline Error",
            str(exc),
            extra_lines=[
                f"Step: {engine.state.current_step.value}",
                "",
                "Traceback:",
                traceback.format_exc(),
            ],
        )
        raise SystemExit(1) from exc


# ---------------------------------------------------------------------------
# validate command
# ---------------------------------------------------------------------------


@main.command()
@click.argument(
    "config_path",
    type=click.Path(exists=False, dir_okay=False, path_type=Path),
)
def validate(config_path: Path) -> None:
    """Validate a deal-config.json file and print the results."""
    try:
        deal_config = load_deal_config(config_path)
    except ConfigFileNotFoundError as exc:
        _print_error("Config Error", str(exc))
        raise SystemExit(1) from exc
    except ConfigParseError as exc:
        _print_error("JSON Error", str(exc))
        raise SystemExit(1) from exc
    except ConfigValidationError as exc:
        _print_error("Validation Error", str(exc))
        err_console.print()
        _print_validation_errors(exc)
        raise SystemExit(1) from exc

    console.print("[bold green]Config is valid.[/bold green]")
    _print_config_summary(deal_config)


# ---------------------------------------------------------------------------
# version command
# ---------------------------------------------------------------------------


@main.command()
def version() -> None:
    """Print the dd-agents version."""
    console.print(f"dd-agents {dd_agents.__version__}")


# ---------------------------------------------------------------------------
# init command
# ---------------------------------------------------------------------------


@main.command()
@click.option(
    "--data-room",
    "data_room",
    type=click.Path(exists=False, file_okay=False, path_type=Path),
    default=None,
    help="Path to the folder containing due diligence files (the data room).",
)
@click.option(
    "--buyer",
    default=None,
    help="Name of the acquiring/buying company.",
)
@click.option(
    "--target",
    default=None,
    help="Name of the company being acquired/evaluated.",
)
@click.option(
    "--deal-type",
    "deal_type",
    type=click.Choice(
        ["acquisition", "merger", "divestiture", "investment", "joint_venture", "other"],
        case_sensitive=False,
    ),
    default=None,
    help="Type of deal (e.g. acquisition, merger). Default: acquisition.",
)
@click.option(
    "--focus-areas",
    "focus_areas",
    default=None,
    help=(
        "Comma-separated list of areas to analyze, e.g. "
        "'ip_ownership,revenue_recognition'. "
        "Options: change_of_control_clauses, ip_ownership, revenue_recognition, "
        "customer_concentration, auto_renewal_terms, data_privacy_compliance, "
        "liability_caps, non_compete_agreements."
    ),
)
@click.option(
    "--name-variants",
    "name_variants",
    default=None,
    help=(
        "Comma-separated alternate names the target company may appear as in contracts, "
        "e.g. 'Acme Inc.,Acme Corporation,ACME'."
    ),
)
@click.option(
    "--output",
    "output_path",
    type=click.Path(dir_okay=False, path_type=Path),
    default=Path("deal-config.json"),
    show_default=True,
    help="Where to save the generated config file.",
)
@click.option(
    "--non-interactive",
    "non_interactive",
    is_flag=True,
    default=False,
    help="Skip all prompts; use flag values only (for scripts and automation).",
)
@click.option(
    "--force",
    is_flag=True,
    default=False,
    help="Overwrite output file if it already exists.",
)
def init(
    data_room: Path | None,
    buyer: str | None,
    target: str | None,
    deal_type: str | None,
    focus_areas: str | None,
    name_variants: str | None,
    output_path: Path,
    non_interactive: bool,
    force: bool,
) -> None:
    """Generate a deal-config.json by scanning a data room.

    Scans your data room folder, asks a few questions about the deal,
    and creates a ready-to-use config file. Run this first to get started.

    \b
    Quick start (interactive):
        dd-agents init

    \b
    Quick start (scripted):
        dd-agents init --non-interactive --data-room ./data_room \\
            --buyer "Buyer Co" --target "Target Co"
    """
    from dd_agents.cli_init import (
        DEFAULT_FOCUS_AREAS,
        build_config_dict,
        print_scan_summary,
        prompt_deal_type,
        prompt_focus_areas,
        scan_data_room,
        write_config,
    )

    console.print("\n[bold]dd-agents init[/bold] -- Generate a deal-config.json\n")

    # --- Collect data room path ---
    if data_room is None:
        if non_interactive:
            _print_error("Missing Option", "--data-room is required in non-interactive mode")
            raise SystemExit(1)
        raw_path = input("Where is your data room? ").strip()
        if not raw_path:
            _print_error("Missing Input", "Data room path is required.")
            raise SystemExit(1)
        data_room = Path(raw_path)

    data_room = data_room.resolve()
    if not data_room.is_dir():
        _print_error("Data Room Error", f"Directory does not exist: {data_room}")
        raise SystemExit(1)

    # --- Scan ---
    console.print("Scanning data room...")
    scan_result = scan_data_room(data_room)
    print_scan_summary(console, scan_result)

    # --- Collect buyer ---
    if buyer is None:
        if non_interactive:
            _print_error("Missing Option", "--buyer is required in non-interactive mode")
            raise SystemExit(1)
        buyer = input("Buyer company name: ").strip()
        if not buyer:
            _print_error("Missing Input", "Buyer name is required.")
            raise SystemExit(1)

    # --- Collect target ---
    if target is None:
        if non_interactive:
            _print_error("Missing Option", "--target is required in non-interactive mode")
            raise SystemExit(1)
        target = input("Target company name: ").strip()
        if not target:
            _print_error("Missing Input", "Target name is required.")
            raise SystemExit(1)

    # --- Collect deal type ---
    if deal_type is None:
        deal_type = "acquisition" if non_interactive else prompt_deal_type(console)

    # --- Collect focus areas ---
    if focus_areas is not None:
        focus_list = [a.strip() for a in focus_areas.split(",") if a.strip()]
    elif non_interactive:
        focus_list = DEFAULT_FOCUS_AREAS[:4]
    else:
        focus_list = prompt_focus_areas(console)

    if not focus_list:
        focus_list = DEFAULT_FOCUS_AREAS[:4]

    # --- Collect name variants ---
    variant_list: list[str] | None = None
    if name_variants is not None:
        variant_list = [v.strip() for v in name_variants.split(",") if v.strip()] or None
    elif not non_interactive:
        console.print(
            "\nThe target company may appear under different names in contracts"
            f"\n(e.g. '{target} Inc.', '{target} Corporation', abbreviations)."
        )
        raw_variants = input("Alternate names (comma-separated, or Enter to skip): ").strip()
        if raw_variants:
            variant_list = [v.strip() for v in raw_variants.split(",") if v.strip()] or None

    # --- Build config ---
    config_dict = build_config_dict(
        buyer=buyer,
        target=target,
        deal_type=deal_type,
        focus_areas=focus_list,
        name_variants=variant_list,
        scan_result=scan_result,
        data_room_path=str(data_room),
    )

    # --- Validate and write ---
    success = write_config(config_dict, output_path, console, err_console, force=force, non_interactive=non_interactive)
    if not success:
        raise SystemExit(1)


# ---------------------------------------------------------------------------
# auto-config command
# ---------------------------------------------------------------------------


@main.command("auto-config")
@click.argument("buyer")
@click.argument("target")
@click.option(
    "--data-room",
    "data_room",
    required=True,
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    help="Path to the data room folder.",
)
@click.option(
    "--deal-type",
    "deal_type",
    type=click.Choice(
        ["acquisition", "merger", "divestiture", "investment", "joint_venture", "other"],
        case_sensitive=False,
    ),
    default=None,
    help="Override the inferred deal type.",
)
@click.option(
    "--output",
    "output_path",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="Where to save the generated config (default: deal-config.json).",
)
@click.option(
    "--dry-run",
    "dry_run",
    is_flag=True,
    default=False,
    help="Print the generated config without writing to disk.",
)
@click.option(
    "--force",
    is_flag=True,
    default=False,
    help="Overwrite output file if it already exists.",
)
@click.option(
    "--verbose",
    "-v",
    is_flag=True,
    default=False,
    help="Enable verbose logging output.",
)
def auto_config(
    buyer: str,
    target: str,
    data_room: Path,
    deal_type: str | None,
    output_path: Path | None,
    dry_run: bool,
    force: bool,
    verbose: bool,
) -> None:
    """Auto-generate deal-config.json by analyzing a data room with AI.

    BUYER is the name of the acquiring company.
    TARGET is the name of the company being acquired/evaluated.

    \b
    Example:
        dd-agents auto-config "Apex Holdings" "WidgetCo" --data-room ./data_room
        dd-agents auto-config "Apex Holdings" "WidgetCo" --data-room ./data_room --dry-run
    """
    if verbose:
        logging.basicConfig(level=logging.WARNING, format="%(name)s: %(message)s")
        logging.getLogger("dd_agents").setLevel(logging.DEBUG)
        logging.getLogger("claude_agent_sdk").setLevel(logging.WARNING)
        logging.getLogger("asyncio").setLevel(logging.WARNING)

    from dd_agents.cli_auto_config import (
        DataRoomAnalyzer,
        build_reference_file_summary,
        get_tree_output,
        print_auto_config_summary,
        validate_and_fix_config,
    )
    from dd_agents.cli_init import print_scan_summary, scan_data_room, write_config

    if output_path is None:
        output_path = Path("deal-config.json")

    console.print("\n[bold]dd-agents auto-config[/bold] -- AI-powered deal config generation\n")

    # 1. Scan data room
    console.print("Scanning data room...")
    scan_result = scan_data_room(data_room)
    print_scan_summary(console, scan_result)

    # 2. Get tree output
    tree_output = get_tree_output(data_room, max_depth=4)

    # 3. Reference files
    reference_files = build_reference_file_summary(data_room)

    # 4. Analyze with Claude
    analyzer = DataRoomAnalyzer(data_room_path=data_room)

    with console.status("[bold cyan]Analyzing data room with Claude...[/bold cyan]"):
        try:
            config = asyncio.run(
                analyzer.analyze(
                    tree_output=tree_output,
                    scan_result=scan_result,
                    reference_files=reference_files,
                    buyer=buyer,
                    target=target,
                    deal_type_hint=deal_type,
                )
            )
        except Exception as exc:
            _print_error("Analysis Error", f"Claude analysis failed: {exc}")
            raise SystemExit(1) from exc

    # 5. Validate and fix
    try:
        config = validate_and_fix_config(config, scan_result)
    except Exception as exc:
        _print_error("Validation Error", f"Generated config is invalid: {exc}")
        if verbose:
            console.print(f"[dim]Raw config:[/dim]\n{json.dumps(config, indent=2)}")
        raise SystemExit(1) from exc

    # Ensure data_room path is in config
    config.setdefault("data_room", {})["path"] = str(data_room.resolve())

    # 6. Dry run or write
    if dry_run:
        console.print()
        console.print(json.dumps(config, indent=2))
        console.print()
        print_auto_config_summary(console, config, scan_result)
        return

    success = write_config(config, output_path, console, err_console, force=force, non_interactive=True)
    if not success:
        raise SystemExit(1)

    console.print()
    print_auto_config_summary(console, config, scan_result)


# ---------------------------------------------------------------------------
# search command
# ---------------------------------------------------------------------------


@main.command()
@click.argument(
    "prompts_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option(
    "--data-room",
    "data_room",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    required=True,
    help="Path to the data room folder.",
)
@click.option(
    "--output",
    "output_path",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="Excel output path (default: auto-named from prompts file).",
)
@click.option(
    "--groups",
    default=None,
    help="Comma-separated group names to include (case-insensitive partial match). E.g. --groups Commercial",
)
@click.option(
    "--customers",
    default=None,
    help="Comma-separated customer names to filter (case-insensitive partial match).",
)
@click.option(
    "--concurrency",
    type=click.IntRange(1, 20),
    default=5,
    show_default=True,
    help="Maximum parallel API calls.",
)
@click.option(
    "--yes",
    "-y",
    is_flag=True,
    default=False,
    help="Skip cost confirmation prompt.",
)
@click.option(
    "--verbose",
    "-v",
    is_flag=True,
    default=False,
    help="Enable verbose logging output.",
)
def search(
    prompts_path: Path,
    data_room: Path,
    output_path: Path | None,
    groups: str | None,
    customers: str | None,
    concurrency: int,
    yes: bool,
    verbose: bool,
) -> None:
    """Search customer contracts using custom prompts.

    Analyze all (or selected) customers' contracts with the questions
    in PROMPTS_PATH. Produces an Excel report with answers and citations.

    \b
    Example:
        dd-agents search prompts.json --data-room ./data_room
        dd-agents search prompts.json --data-room ./data_room --groups Commercial
        dd-agents search prompts.json --data-room ./data_room --customers "Acme,Beta" -y
    """
    if verbose:
        logging.basicConfig(level=logging.WARNING, format="%(name)s: %(message)s")
        logging.getLogger("dd_agents").setLevel(logging.DEBUG)
        logging.getLogger("claude_agent_sdk").setLevel(logging.WARNING)
        logging.getLogger("asyncio").setLevel(logging.WARNING)

    from dd_agents.search.runner import SearchRunner

    runner = SearchRunner(
        prompts_path=prompts_path,
        data_room_path=data_room,
        output_path=output_path,
        group_filter=groups,
        customer_filter=customers,
        concurrency=concurrency,
        auto_confirm=yes,
        verbose=verbose,
    )
    runner.run()


# ---------------------------------------------------------------------------
# assess command (Issue #149 — Data Room Health Check)
# ---------------------------------------------------------------------------


@main.command()
@click.argument(
    "data_room",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
)
@click.option(
    "--verbose",
    "-v",
    is_flag=True,
    default=False,
    help="Enable verbose logging output.",
)
def assess(data_room: Path, verbose: bool) -> None:
    """Assess data room quality and completeness before running the pipeline.

    Scans the data room folder and produces a health report covering:
    file type distribution, extraction readiness, potential issues,
    and an overall completeness score.

    \b
    Example:
        dd-agents assess ./data_room
    """
    if verbose:
        logging.basicConfig(level=logging.WARNING, format="%(name)s: %(message)s")
        logging.getLogger("dd_agents").setLevel(logging.DEBUG)

    from dd_agents.assessment import DataRoomAssessor

    console.print("\n[bold]dd-agents assess[/bold] -- Data Room Health Check\n")

    assessor = DataRoomAssessor(data_room.resolve())
    report = assessor.assess()

    # Display results
    _print_assessment_report(report)


def _print_assessment_report(report: dict[str, Any]) -> None:
    """Print the data room assessment as a rich panel."""
    score = report.get("overall_score", 0)
    score_color = "green" if score >= 80 else "yellow" if score >= 50 else "red"

    # Summary
    console.print(
        Panel(
            f"[bold {score_color}]Overall Score: {score}/100[/bold {score_color}]\n"
            f"Total files: {report.get('total_files', 0)}\n"
            f"Supported files: {report.get('supported_files', 0)}\n"
            f"Unsupported files: {report.get('unsupported_files', 0)}\n"
            f"Estimated customers: {report.get('estimated_customers', 0)}",
            title="Data Room Assessment",
            border_style=score_color,
        )
    )

    # File type distribution
    file_types = report.get("file_types", {})
    if file_types:
        table = Table(title="File Type Distribution", show_header=True)
        table.add_column("Extension", style="bold")
        table.add_column("Count", justify="right")
        table.add_column("Status")
        for ext, info in sorted(file_types.items(), key=lambda x: x[1]["count"], reverse=True):
            status = "[green]Supported[/green]" if info.get("supported") else "[red]Unsupported[/red]"
            table.add_row(ext, str(info["count"]), status)
        console.print(table)

    # Issues
    issues = report.get("issues", [])
    if issues:
        console.print()
        for issue in issues:
            severity = issue.get("severity", "info")
            color = {"critical": "red", "warning": "yellow", "info": "cyan"}.get(severity, "white")
            console.print(f"  [{color}]{severity.upper()}[/{color}]: {issue['message']}")

    # Recommendations
    recs = report.get("recommendations", [])
    if recs:
        console.print()
        console.print("[bold]Recommendations:[/bold]")
        for rec in recs:
            console.print(f"  - {rec}")

    console.print()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _print_error(
    title: str,
    message: str,
    extra_lines: list[str] | None = None,
) -> None:
    """Print a formatted error panel to stderr."""
    lines = [f"[bold red]{title}:[/bold red] {message}"]
    if extra_lines:
        lines.extend(extra_lines)
    err_console.print(
        Panel(
            "\n".join(lines),
            title="Error",
            border_style="red",
        )
    )


def _print_config_summary(deal_config: object) -> None:
    """Print a rich summary table for a validated DealConfig."""
    from dd_agents.models.config import DealConfig  # noqa: N814

    if not isinstance(deal_config, DealConfig):  # pragma: no cover
        return

    table = Table(title="Deal Configuration Summary", show_header=False, padding=(0, 2))
    table.add_column("Field", style="bold cyan")
    table.add_column("Value")

    table.add_row("Config version", deal_config.config_version)
    table.add_row("Buyer", deal_config.buyer.name)
    table.add_row("Target", deal_config.target.name)
    table.add_row("Deal type", deal_config.deal.type.value)
    table.add_row("Focus areas", ", ".join(deal_config.deal.focus_areas))
    table.add_row(
        "Execution mode",
        deal_config.execution.execution_mode.value,
    )
    table.add_row("Judge enabled", str(deal_config.judge.enabled))
    table.add_row(
        "Subsidiaries",
        ", ".join(deal_config.target.subsidiaries) or "(none)",
    )

    console.print(table)


def _print_validation_errors(exc: ConfigValidationError) -> None:
    """Print structured validation errors using rich."""
    table = Table(title="Validation Errors", show_header=True)
    table.add_column("Location", style="bold")
    table.add_column("Message", style="red")
    table.add_column("Type", style="dim")

    for err in exc.validation_error.errors():
        loc = " -> ".join(str(part) for part in err["loc"])
        table.add_row(loc, err["msg"], err["type"])

    err_console.print(table)


def _print_dry_run(deal_config: object, resume_from: int) -> None:
    """Print what would happen without actually running."""
    from dd_agents.models.config import DealConfig
    from dd_agents.orchestrator.steps import PipelineStep

    console.print(
        Panel(
            "[bold cyan]Dry run mode[/bold cyan] -- no pipeline execution",
            title="Dry Run",
            border_style="cyan",
        )
    )

    table = Table(title="Pipeline Steps", show_header=True)
    table.add_column("#", style="bold", width=4)
    table.add_column("Step", min_width=30)
    table.add_column("Type", width=12)
    table.add_column("Status", width=12)

    for step in PipelineStep:
        num = step.step_number
        label = step.value

        if step.is_blocking_gate:
            step_type = "[red]BLOCKING[/red]"
        elif step.is_conditional:
            step_type = "[yellow]COND[/yellow]"
        else:
            step_type = ""

        if num < resume_from:
            status = "[dim]skipped[/dim]"
        else:
            # Determine if conditional step would run
            will_skip = False
            if isinstance(deal_config, DealConfig):
                if step == PipelineStep.CONTRACT_DATE_RECONCILIATION:
                    has_db = bool(deal_config.model_dump().get("source_of_truth", {}).get("customer_database"))
                    if not has_db:
                        will_skip = True

                is_incremental = deal_config.execution.execution_mode.value == "incremental"
                if step == PipelineStep.INCREMENTAL_CLASSIFICATION and not is_incremental:
                    will_skip = True

                if step == PipelineStep.INCREMENTAL_MERGE and not is_incremental:
                    will_skip = True

                judge_steps = {
                    PipelineStep.SPAWN_JUDGE,
                    PipelineStep.JUDGE_REVIEW,
                    PipelineStep.JUDGE_RESPAWN,
                    PipelineStep.JUDGE_ROUND2,
                }
                if step in judge_steps and not deal_config.judge.enabled:
                    will_skip = True

            status = "[yellow]skip[/yellow]" if will_skip else "[green]run[/green]"

        table.add_row(str(num), label, step_type, status)

    console.print(table)

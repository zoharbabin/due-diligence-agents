"""Click CLI entry point for the dd-agents pipeline.

Registered as ``dd-agents`` console script via pyproject.toml.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import traceback
from pathlib import Path
from typing import Any

import click
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table

import dd_agents
from dd_agents.config import (
    ConfigFileNotFoundError,
    ConfigParseError,
    ConfigValidationError,
    load_deal_config,
)
from dd_agents.utils.constants import SEVERITY_P0, SEVERITY_P1, SEVERITY_P2

logger = logging.getLogger(__name__)
console = Console()
err_console = Console(stderr=True)


def _terminate_child_processes() -> None:
    """Send SIGTERM to all descendant processes of the current PID.

    SDK JS (Bun) subprocesses survive ``os._exit()`` and keep printing
    "Stream closed" errors.  Also kills grandchildren — the claude CLI
    subprocess spawns Bun.js workers that become orphans (reparented to
    PID 1) if the parent dies first.

    Uses ``pkill -P`` recursively: first kill grandchildren (children of
    our children), then kill direct children.  This bottom-up order
    avoids creating new orphans.
    """
    import os
    import signal
    import subprocess

    my_pid = str(os.getpid())
    try:
        # Find direct children.
        result = subprocess.run(
            ["pgrep", "-P", my_pid],
            capture_output=True,
            text=True,
        )
        child_pids = [line.strip() for line in result.stdout.strip().splitlines() if line.strip()]

        # Kill grandchildren first (bottom-up).
        for cpid in child_pids:
            try:
                gc_result = subprocess.run(
                    ["pgrep", "-P", cpid],
                    capture_output=True,
                    text=True,
                )
                for gc_line in gc_result.stdout.strip().splitlines():
                    gc_pid = gc_line.strip()
                    if gc_pid:
                        with contextlib.suppress(OSError):
                            os.kill(int(gc_pid), signal.SIGTERM)
            except Exception:  # noqa: BLE001
                pass

        # Kill direct children.
        for cpid in child_pids:
            with contextlib.suppress(OSError):
                os.kill(int(cpid), signal.SIGTERM)
    except Exception:  # noqa: BLE001
        pass


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
    metavar="CONFIG_PATH",
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
    help="Resume pipeline from a specific step number (0-35).",
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
    "--no-knowledge",
    "no_knowledge",
    is_flag=True,
    default=False,
    help="Skip knowledge compilation after pipeline run.",
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
    help="Per-agent model override in agent=model format (e.g. --model-override legal=claude-sonnet-4-20250514).",
)
def run(
    config_path: Path,
    mode: str | None,
    verbose: bool,
    resume_from: int,
    dry_run: bool,
    quick_scan: bool,
    no_knowledge: bool,
    model_profile: str | None,
    model_overrides: tuple[str, ...],
) -> None:
    """Run the due diligence pipeline with a deal-config.json file."""
    # --- Load and validate config ---
    try:
        deal_config = load_deal_config(config_path)
    except ConfigFileNotFoundError as exc:
        _print_error(
            "Config Error",
            f"{exc}\n"
            "  To generate a config: dd-agents init --data-room ./your_data_room\n"
            "  Or with AI assistance: dd-agents auto-config buyer target --data-room ./your_data_room",
        )
        raise SystemExit(1) from exc
    except ConfigParseError as exc:
        _print_error(
            "JSON Error",
            f"{exc}\n  Verify the file is valid JSON (try: python -m json.tool your-config.json)",
        )
        raise SystemExit(1) from exc
    except ConfigValidationError as exc:
        _print_error(
            "Validation Error",
            f"{exc}\n  To generate a valid config: dd-agents init --data-room ./your_data_room",
        )
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
        from dd_agents.models.enums import AgentName

        valid_agents = tuple(e.value for e in AgentName)
        for override in model_overrides:
            if "=" not in override:
                _print_error(
                    "Invalid Option",
                    f"--model-override must be agent=model format, got: '{override}'\n"
                    f"  Example: --model-override legal=claude-haiku-4-5-20251001\n"
                    f"  Valid agents: {', '.join(valid_agents)}",
                )
                raise SystemExit(1)
            agent_name, model_id = override.split("=", 1)
            agent_name = agent_name.strip()
            model_id = model_id.strip()
            if not agent_name or not model_id:
                _print_error(
                    "Invalid Option",
                    f"--model-override requires both agent and model, got: '{override}'\n"
                    f"  Example: --model-override legal=claude-haiku-4-5-20251001\n"
                    f"  Valid agents: {', '.join(valid_agents)}",
                )
                raise SystemExit(1)
            deal_config.agent_models.overrides[agent_name] = model_id

    _print_config_summary(deal_config)

    # --- Validate resume-from ---
    if resume_from < 0 or resume_from > 35:
        _print_error(
            "Invalid Option",
            f"--resume-from must be 0-35, got {resume_from}\n"
            "  Key steps: 0=start, 6=inventory, 14=prompts, 16=agents, 24=merge, 28=QA, 35=end",
        )
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
        source = "data_room.path in config" if data_room_path_str else "config file parent directory"
        _print_error(
            "Data Room Error",
            f"Data room directory does not exist: {project_dir}\n"
            f"  Source: {source}\n"
            "  Check that the path in your deal-config.json is correct, or run from the data room directory.\n"
            "  To check data room quality first: dd-agents assess ./your_data_room",
        )
        raise SystemExit(1)

    # --- Set up logging: always write to file, -v adds terminal output ---
    from dd_agents.cli_logging import close_pipeline_logging, setup_pipeline_logging

    log_dir = project_dir / "_dd" / "forensic-dd"
    log_path = setup_pipeline_logging(log_dir=log_dir, verbose=verbose)

    # --- Run pipeline ---
    from dd_agents.errors import BlockingGateError
    from dd_agents.orchestrator.engine import PipelineEngine

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
    if no_knowledge:
        run_options["no_knowledge"] = True

    console.print()
    console.print(
        Panel(
            f"[bold green]Starting pipeline[/bold green]\n"
            f"Project: {project_dir}\n"
            f"Mode: {deal_config.execution.execution_mode.value}\n"
            f"Resume from: {'step ' + str(resume_from) if resume_from else 'beginning'}\n"
            f"Log: {log_path}",
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

        summary_parts.append(f"  Log: [link=file://{log_path}]{log_path}[/link]")

        console.print(
            Panel(
                "\n".join(summary_parts),
                title="Complete",
                border_style="green",
            )
        )
        close_pipeline_logging()

        # Kill orphaned SDK JS (Bun) subprocesses that keep printing
        # "Stream closed" errors after session teardown, then force-exit.
        # All pipeline work is complete and flushed at this point.
        _terminate_child_processes()
        import os as _os

        _os._exit(0)

    except BlockingGateError as exc:
        console.print()
        _print_error(
            "Blocking Gate Failed",
            str(exc),
            extra_lines=[
                f"Step: {engine.state.current_step.value}",
                "The pipeline cannot continue past this blocking gate.",
                "",
                f"Full log: {log_path}",
                "",
                "To resume from a specific step after fixing the issue:",
                f"  dd-agents run {config_path} --resume-from {engine.state.current_step.step_number}",
            ],
        )
        close_pipeline_logging()
        raise SystemExit(2) from exc

    except KeyboardInterrupt:
        console.print()
        console.print(
            Panel(
                "[bold yellow]Pipeline interrupted by user[/bold yellow]\n"
                f"Last completed step: {engine.state.current_step.value}\n"
                f"Log: {log_path}\n"
                "\nTo resume:\n"
                f"  dd-agents run {config_path} --resume-from {engine.state.current_step.step_number}",
                title="Interrupted",
                border_style="yellow",
            )
        )
        close_pipeline_logging()
        _terminate_child_processes()
        import os as _os

        _os._exit(130)

    except Exception as exc:
        console.print()
        _print_error(
            "Pipeline Error",
            str(exc),
            extra_lines=[
                f"Step: {engine.state.current_step.value}",
                "",
                f"Full log: {log_path}",
                "",
                "Traceback:",
                traceback.format_exc(),
            ],
        )
        close_pipeline_logging()
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
        ["acquisition", "asset_sale", "merger", "divestiture", "investment", "joint_venture", "other"],
        case_sensitive=False,
    ),
    default=None,
    help="Type of deal (e.g. acquisition, asset_sale, merger). Default: acquisition.",
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
            _print_error(
                "Missing Option",
                "--data-room is required in non-interactive mode\n"
                "  Example: dd-agents init --non-interactive --data-room ./data_room "
                '--buyer "Buyer Co" --target "Target Co"',
            )
            raise SystemExit(1)
        raw_path = input("Where is your data room? ").strip()
        if not raw_path:
            _print_error(
                "Missing Input",
                "Data room path is required.\n"
                "  Point to a folder containing contracts organized by subject:\n"
                "    ./data_room/Subject_A/contract.pdf\n"
                "    ./data_room/Subject_B/agreement.docx",
            )
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
        ["acquisition", "asset_sale", "merger", "divestiture", "investment", "joint_venture", "other"],
        case_sensitive=False,
    ),
    default=None,
    help="Override the inferred deal type.",
)
@click.option(
    "--buyer-docs",
    "buyer_docs",
    multiple=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Buyer business description files (10-K, annual report). Repeatable.",
)
@click.option(
    "--spa",
    "spa_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="SPA draft/redline file for deal structure extraction.",
)
@click.option(
    "--press-release",
    "press_release_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="Acquisition press release for strategic context.",
)
@click.option(
    "--buyer-docs-dir",
    "buyer_docs_dir",
    type=str,
    default="_buyer",
    show_default=True,
    help="Folder name for converted buyer files in data room.",
)
@click.option(
    "--interactive",
    is_flag=True,
    default=False,
    help="Enable interactive follow-up questions for strategy refinement.",
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
    buyer_docs: tuple[Path, ...],
    spa_path: Path | None,
    press_release_path: Path | None,
    buyer_docs_dir: str,
    interactive: bool,
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
        dd-agents auto-config "Apex Holdings" "WidgetCo" --data-room ./data_room \\
          --buyer-docs ./10k.docx --spa ./spa.pdf --press-release ./pr.docx
    """
    if verbose:
        logging.basicConfig(level=logging.WARNING, format="%(name)s: %(message)s")
        logging.getLogger("dd_agents").setLevel(logging.DEBUG)
        logging.getLogger("claude_agent_sdk").setLevel(logging.WARNING)
        logging.getLogger("asyncio").setLevel(logging.WARNING)

    from dd_agents.cli_auto_config import (
        BuyerContextIngester,
        DataRoomAnalyzer,
        build_reference_file_summary,
        get_tree_output,
        print_auto_config_summary,
        run_interactive_refinement,
        validate_and_fix_config,
    )
    from dd_agents.cli_init import print_scan_summary, scan_data_room, write_config

    if output_path is None:
        output_path = Path("deal-config.json")

    console.print("\n[bold]dd-agents auto-config[/bold] -- AI-powered deal config generation\n")

    # 1. Ingest buyer context documents (if provided)
    ingested_context = None
    has_buyer_context = bool(buyer_docs or spa_path or press_release_path)
    if has_buyer_context:
        console.print("Ingesting buyer context documents...")
        ingester = BuyerContextIngester()
        ingested_context = ingester.ingest(
            data_room_path=data_room,
            buyer_docs=list(buyer_docs) if buyer_docs else None,
            spa_path=spa_path,
            press_release_path=press_release_path,
            buyer_docs_dir=buyer_docs_dir,
        )
        if ingested_context.buyer_doc_paths:
            console.print(f"  Converted {len(ingested_context.buyer_doc_paths)} buyer doc(s) to {buyer_docs_dir}/")
        if ingested_context.spa_content:
            console.print(f"  Extracted SPA content ({len(ingested_context.spa_content):,} chars)")
        if ingested_context.press_release_content:
            console.print(f"  Extracted press release ({len(ingested_context.press_release_content):,} chars)")

    # 2. Scan data room
    console.print("Scanning data room...")
    scan_result = scan_data_room(data_room)
    print_scan_summary(console, scan_result)

    # 3. Get tree output
    tree_output = get_tree_output(data_room, max_depth=4)

    # 4. Reference files
    reference_files = build_reference_file_summary(data_room)

    # 5. Analyze with Claude (multi-turn when buyer context provided)
    analyzer = DataRoomAnalyzer(data_room_path=data_room)

    turns_desc = "multi-turn analysis" if has_buyer_context else "analysis"
    with console.status(f"[bold cyan]Running {turns_desc} with Claude...[/bold cyan]"):
        try:
            config = asyncio.run(
                analyzer.analyze(
                    tree_output=tree_output,
                    scan_result=scan_result,
                    reference_files=reference_files,
                    buyer=buyer,
                    target=target,
                    deal_type_hint=deal_type,
                    ingested_context=ingested_context,
                )
            )
        except Exception as exc:
            _print_error("Analysis Error", f"Claude analysis failed: {exc}")
            raise SystemExit(1) from exc

    # 6. Interactive refinement (if requested and buyer_strategy exists)
    if interactive and config.get("buyer_strategy"):
        config = run_interactive_refinement(config, console)

    # 7. Validate and fix
    try:
        config = validate_and_fix_config(config, scan_result)
    except Exception as exc:
        _print_error("Validation Error", f"Generated config is invalid: {exc}")
        if verbose:
            console.print(f"[dim]Raw config:[/dim]\n{json.dumps(config, indent=2)}")
        raise SystemExit(1) from exc

    # Ensure data_room path is in config
    config.setdefault("data_room", {})["path"] = str(data_room.resolve())

    # 8. Dry run or write
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

    # Kill orphaned SDK JS (Bun) subprocesses that survive normal exit.
    _terminate_child_processes()


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
    "--subjects",
    default=None,
    help="Comma-separated subject names to filter (case-insensitive partial match).",
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
    "--no-file",
    "no_file",
    is_flag=True,
    default=False,
    help="Skip filing search results back to the knowledge base.",
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
    subjects: str | None,
    concurrency: int,
    yes: bool,
    no_file: bool,
    verbose: bool,
) -> None:
    """Search subject contracts using custom prompts.

    Analyze all (or selected) subjects' contracts with the questions
    in PROMPTS_PATH. Produces an Excel report with answers and citations.

    \b
    Example:
        dd-agents search prompts.json --data-room ./data_room
        dd-agents search prompts.json --data-room ./data_room --groups Commercial
        dd-agents search prompts.json --data-room ./data_room --subjects "Acme,Beta" -y
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
        subject_filter=subjects,
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
            f"Estimated subjects: {report.get('estimated_subjects', 0)}",
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
# export-pdf command (Issue #151)
# ---------------------------------------------------------------------------


@main.command("export-pdf")
@click.argument(
    "html_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option(
    "--output",
    "output_path",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="Output PDF path (default: same name with .pdf extension).",
)
@click.option(
    "--engine",
    type=click.Choice(["auto", "playwright", "weasyprint"]),
    default="auto",
    show_default=True,
    help="PDF rendering engine to use.",
)
def export_pdf(html_path: Path, output_path: Path | None, engine: str) -> None:
    """Export an HTML DD report to PDF.

    Converts the self-contained HTML report to a print-optimized PDF
    using Playwright (preferred) or WeasyPrint (fallback).

    \b
    Example:
        dd-agents export-pdf report.html
        dd-agents export-pdf report.html --output board-package.pdf
        dd-agents export-pdf report.html --engine weasyprint
    """
    from dd_agents.reporting.pdf_export import PDFExportError
    from dd_agents.reporting.pdf_export import export_pdf as do_export

    console.print("\n[bold]dd-agents export-pdf[/bold]\n")

    with console.status("[bold cyan]Generating PDF...[/bold cyan]"):
        try:
            result = asyncio.run(do_export(html_path, output_path, engine=engine))
        except PDFExportError as exc:
            _print_error("PDF Export Failed", str(exc))
            raise SystemExit(1) from exc
        except FileNotFoundError as exc:
            _print_error("File Not Found", str(exc))
            raise SystemExit(1) from exc

    size_kb = result.stat().st_size / 1024
    console.print(
        Panel(
            f"[bold green]PDF exported successfully[/bold green]\n\nOutput: {result}\nSize: {size_kb:.1f} KB",
            title="Export Complete",
            border_style="green",
        )
    )


# ---------------------------------------------------------------------------
# query command (Issue #124)
# ---------------------------------------------------------------------------


@main.command()
@click.option(
    "--report",
    "report_dir",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    required=True,
    help="Path to the pipeline run directory (contains findings/merged/).",
)
@click.option(
    "--question",
    "-q",
    default=None,
    help="Single question to ask. Omit for interactive mode.",
)
@click.option(
    "--verbose",
    "-v",
    is_flag=True,
    default=False,
    help="Enable verbose logging output.",
)
def query(report_dir: Path, question: str | None, verbose: bool) -> None:
    """Ask natural-language questions about the DD report.

    Index the merged findings from a pipeline run and answer
    questions interactively or via the --question flag.

    \b
    Example:
        dd-agents query --report _dd/forensic-dd/runs/latest --question "How many P0 findings?"
        dd-agents query --report _dd/forensic-dd/runs/latest  # interactive mode
    """
    if verbose:
        logging.basicConfig(level=logging.WARNING, format="%(name)s: %(message)s")
        logging.getLogger("dd_agents").setLevel(logging.DEBUG)

    from dd_agents.query.engine import QueryEngine
    from dd_agents.query.indexer import FindingIndexer

    console.print("\n[bold]dd-agents query[/bold]\n")

    indexer = FindingIndexer()
    with console.status("[bold cyan]Indexing findings...[/bold cyan]"):
        index = indexer.index_report(report_dir)

    console.print(f"[dim]{index.summary}[/dim]\n")

    if index.total_findings == 0:
        console.print("[yellow]No findings found. Check the --report path.[/yellow]")
        raise SystemExit(1)

    engine = QueryEngine(index, verbose=verbose)

    if question:
        # Single-question mode
        result = asyncio.run(engine.query(question))
        _print_query_result(question, result)
    else:
        # Interactive mode
        console.print("[dim]Type your question (or 'quit' to exit):[/dim]\n")
        while True:
            try:
                user_input = console.input("[bold cyan]> [/bold cyan]")
            except (EOFError, KeyboardInterrupt):
                console.print("\n[dim]Goodbye.[/dim]")
                break

            user_input = user_input.strip()
            if not user_input:
                continue
            if user_input.lower() in ("quit", "exit", "q"):
                console.print("[dim]Goodbye.[/dim]")
                break

            result = asyncio.run(engine.query(user_input))
            _print_query_result(user_input, result)
            console.print()

    # Kill orphaned SDK JS (Bun) subprocesses that survive normal exit.
    _terminate_child_processes()


def _print_query_result(question: str, result: Any) -> None:
    """Print a query result as a rich panel."""
    conf_color = {"high": "green", "medium": "yellow", "low": "red"}.get(result.confidence, "white")

    console.print(
        Panel(
            Markdown(result.answer),
            title=f"Q: {question}",
            subtitle=f"[{conf_color}]confidence: {result.confidence}[/{conf_color}] | type: {result.query_type}",
            border_style="blue",
        )
    )

    if result.sources:
        table = Table(show_header=True, title="Supporting Findings")
        table.add_column("Severity", width=8)
        table.add_column("Entity")
        table.add_column("Title")
        table.add_column("Category")
        for src in result.sources[:5]:
            sev = src.get("severity", "")
            sev_color = {SEVERITY_P0: "red", SEVERITY_P1: "bright_red", SEVERITY_P2: "yellow"}.get(sev, "white")
            table.add_row(
                f"[{sev_color}]{sev}[/{sev_color}]",
                src.get("subject", ""),
                src.get("title", ""),
                src.get("category", ""),
            )
        console.print(table)


# ---------------------------------------------------------------------------
# Chat query runner with Esc cancellation
# ---------------------------------------------------------------------------


def _print_stderr_log() -> None:
    """Print the contents of the stderr log file for verbose diagnostics."""
    import os

    log_path = os.path.join(os.path.expanduser("~"), ".dd-agents-chat-stderr.log")
    try:
        with open(log_path, encoding="utf-8", errors="replace") as f:
            content = f.read().strip()
        if content:
            console.print("\n[bold dim]── stderr log ──[/bold dim]")
            for line in content.splitlines()[-30:]:
                console.print(f"[dim]{line}[/dim]")
            console.print("[bold dim]── end stderr ──[/bold dim]")
        else:
            console.print("[dim]stderr log: (empty)[/dim]")
    except OSError:
        console.print("[dim]stderr log: (not found)[/dim]")


def _run_chat_query(
    engine: Any,
    user_input: str,
    on_tool_status: Any,
    spinner: Any,
) -> Any:
    """Run a chat query in a background thread, watching for Esc to cancel.

    Returns:
        ChatResponse on success, ``None`` if cancelled by Esc,
        or an error message string on failure.
    """
    import os
    import select
    import sys
    import threading

    result: dict[str, Any] = {"response": None, "error": None}
    done = threading.Event()

    # Redirect fd 2 to a log file so the SDK subprocess's stderr is
    # captured for diagnosis instead of corrupting the terminal.
    _stderr_log_path = os.path.join(os.path.expanduser("~"), ".dd-agents-chat-stderr.log")
    _original_stderr_fd: int | None = None
    _stderr_log_fd: int | None = None
    try:
        _original_stderr_fd = os.dup(2)
        _stderr_log_fd = os.open(_stderr_log_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
        os.dup2(_stderr_log_fd, 2)
    except OSError:
        # If stderr redirect fails, continue without it — the worst
        # that happens is some SDK noise on the terminal.
        pass

    def _query() -> None:
        try:
            result["response"] = asyncio.run(engine.ask(user_input, on_tool_status=on_tool_status))
        except Exception as exc:
            result["error"] = str(exc)
        finally:
            done.set()

    thread = threading.Thread(target=_query, daemon=True)
    thread.start()

    # Watch for Esc key while the query runs.
    # Esc = 0x1b.  Escape *sequences* (arrow keys, etc.) send 0x1b
    # followed immediately by more bytes, so we wait 50 ms after
    # receiving 0x1b — if nothing follows, it was a bare Esc press.
    cancelled = False
    try:
        import termios
        import tty

        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        try:
            tty.setcbreak(fd)
            while not done.is_set():
                readable, _, _ = select.select([sys.stdin], [], [], 0.15)
                if readable:
                    ch = sys.stdin.read(1)
                    if ch == "\x1b":
                        # Bare Esc? Wait briefly for escape-sequence bytes.
                        more, _, _ = select.select([sys.stdin], [], [], 0.05)
                        if not more:
                            cancelled = True
                            break
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
    except (ImportError, OSError, ValueError):
        # Not a terminal (piped input, Windows, etc.) — just wait.
        done.wait()

    # Restore stderr — always clean up fds, even on cancel/error.
    if _original_stderr_fd is not None:
        os.dup2(_original_stderr_fd, 2)
        os.close(_original_stderr_fd)
    if _stderr_log_fd is not None:
        os.close(_stderr_log_fd)

    if cancelled:
        spinner.stop()
        # Kill orphaned SDK subprocess so the daemon thread can exit.
        _terminate_child_processes()
        thread.join(timeout=5)
        return None

    # Wait for the thread to finish — if the SDK hangs, time out.
    thread.join(timeout=60)
    if not done.is_set():
        # Thread timed out — kill the subprocess so the thread can exit.
        _terminate_child_processes()
        thread.join(timeout=5)

    if result["error"]:
        return result["error"]
    if result["response"] is not None:
        return result["response"]
    # Thread timed out or produced nothing — treat as error
    return "The agent timed out. Try a simpler question or restart the session."


# ---------------------------------------------------------------------------
# chat command
# ---------------------------------------------------------------------------


@main.command()
@click.option(
    "--report",
    "report_dir",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=None,
    help="Path to the pipeline run directory. Default: runs/latest.",
)
@click.option(
    "--model",
    "model",
    default=None,
    help="Override the LLM model for chat (e.g. claude-sonnet-4-6).",
)
@click.option(
    "--max-cost",
    "max_cost",
    type=float,
    default=2.0,
    show_default=True,
    help="Maximum session cost in USD.",
)
@click.option(
    "--no-tools",
    "no_tools",
    is_flag=True,
    default=False,
    help="Disable document tools (findings-only mode).",
)
@click.option(
    "--verbose",
    "-v",
    is_flag=True,
    default=False,
    help="Enable verbose logging output.",
)
def chat(
    report_dir: Path | None,
    model: str | None,
    max_cost: float,
    no_tools: bool,
    verbose: bool,
) -> None:
    """Interactive chat about due diligence findings.

    Start a multi-turn conversation about the DD analysis results.
    Ask questions about findings, drill into documents, verify citations.
    Insights are automatically saved as persistent memories across sessions.

    \b
    Example:
        dd-agents chat
        dd-agents chat --report _dd/forensic-dd/runs/latest
        dd-agents chat --no-tools
        dd-agents chat --max-cost 5.0 --model claude-sonnet-4-6
    """
    if verbose:
        logging.basicConfig(level=logging.WARNING, format="%(name)s: %(message)s")
        logging.getLogger("dd_agents").setLevel(logging.DEBUG)

    from dd_agents.chat import ChatConfig, ChatEngine

    # Resolve report directory
    if report_dir is None:
        candidates = [
            Path("_dd/forensic-dd/runs/latest"),
            Path("runs/latest"),
        ]
        for c in candidates:
            if c.exists():
                report_dir = c.resolve()
                break
        if report_dir is None:
            _print_error(
                "No Report",
                "No --report specified and no runs/latest found.\n"
                "  Run the pipeline first: dd-agents run deal-config.json\n"
                "  Or specify: dd-agents chat --report /path/to/run",
            )
            raise SystemExit(1)

    # Resolve project directory (parent of _dd/)
    project_dir = report_dir
    for _ in range(5):
        if (project_dir / "_dd").is_dir():
            break
        project_dir = project_dir.parent
    else:
        project_dir = report_dir.parent

    config = ChatConfig(
        model=model,
        max_session_cost=max_cost,
        enable_tools=not no_tools,
        verbose=verbose,
    )

    try:
        engine = ChatEngine(
            run_dir=report_dir,
            project_dir=project_dir,
            config=config,
        )
    except Exception as exc:
        _print_error("Chat Init Error", str(exc))
        raise SystemExit(1) from exc

    # Print banner
    mode_label = "findings + documents" if config.enable_tools else "findings only"
    memory_note = f", {engine.memory_count} memories" if engine.memory_count > 0 else ""
    console.print()
    console.print(
        Panel(
            f"[bold green]DD Chat[/bold green] ({mode_label})\n"
            f"Report: {report_dir}\n"
            f"Findings: {engine.finding_count}{memory_note}\n"
            f"Budget: ${max_cost:.2f}\n"
            f"[bold]Enter[/bold] send · [bold]Shift+Enter[/bold] newline · "
            f"[bold]Esc[/bold] cancel · [bold]Ctrl+C[/bold] exit",
            title="Chat",
            border_style="green",
        )
    )
    console.print()

    # Build multiline prompt session.
    # Enter (\r = ControlM) = send.
    # Shift+Enter = newline — iTerm2 sends \n (ControlJ) for Shift+Return
    #   via its key binding: Settings > Keys > Key Bindings > Send "\n".
    # Option+Enter (Alt+Enter) = newline (standard terminal fallback).
    from prompt_toolkit import PromptSession
    from prompt_toolkit.key_binding import KeyBindings

    _kb = KeyBindings()

    @_kb.add("enter", eager=True)
    def _kb_submit(event: Any) -> None:
        """Enter (\r) = send message."""
        event.current_buffer.validate_and_handle()

    @_kb.add("c-j")
    def _kb_newline_shift_enter(event: Any) -> None:
        """Shift+Enter — iTerm2 sends \n (ControlJ) for Shift+Return."""
        event.current_buffer.insert_text("\n")

    @_kb.add("escape", "enter")
    def _kb_newline_alt_enter(event: Any) -> None:
        """Option+Enter (Alt+Enter) — standard terminal fallback."""
        event.current_buffer.insert_text("\n")

    _prompt_session: PromptSession[str] = PromptSession(
        multiline=True,
        key_bindings=_kb,
        prompt_continuation="  ",
    )

    # Human-readable labels for tool status updates
    _tool_labels: dict[str, str] = {
        "verify_citation": "Verifying citation",
        "search_in_file": "Searching in file",
        "get_page_content": "Reading page",
        "read_office": "Reading document",
        "get_subject_files": "Looking up files",
        "resolve_entity": "Resolving entity",
        "search_similar": "Searching similar",
        "batch_verify_citations": "Verifying citations",
        "save_memory": "Saving memory",
        "search_chat_memory": "Searching memories",
        "flag_finding": "Flagging finding",
        "list_corrections": "Loading corrections",
        "Read": "Reading file",
        "Glob": "Searching files",
        "Grep": "Searching content",
    }

    # Interactive loop
    _prefill = ""
    while True:
        try:
            user_input = _prompt_session.prompt("> ", default=_prefill)
            _prefill = ""
        except KeyboardInterrupt:
            # Ctrl+C = close app
            console.print("\n[dim]Goodbye.[/dim]")
            break
        except EOFError:
            console.print("\n[dim]Goodbye.[/dim]")
            break

        user_input = user_input.strip()
        if not user_input:
            continue
        if user_input.lower() in ("quit", "exit", "q"):
            console.print("[dim]Goodbye.[/dim]")
            break
        if user_input.lower() == "cost":
            console.print(f"[dim]Session cost: ${engine.session_cost:.4f} / ${max_cost:.2f}[/dim]")
            continue
        if user_input.lower() == "history":
            console.print(f"[dim]Turns: {engine.turn_count}, History: {engine.history_chars} chars[/dim]")
            continue

        spinner = console.status("[dim]Thinking...[/dim]", spinner="dots")
        spinner.start()

        def _on_tool_status(
            tool_name: str,
            _spinner: Any = spinner,
            _labels: dict[str, str] = _tool_labels,
        ) -> None:
            label = _labels.get(tool_name, tool_name.replace("_", " ").title())
            if label.startswith("mcp__"):
                label = label.split("__")[-1].replace("_", " ").title()
            _spinner.update(f"[dim]{label}...[/dim]")

        response = _run_chat_query(engine, user_input, _on_tool_status, spinner)
        spinner.stop()

        # Clean up any lingering SDK subprocesses between queries.
        # Each query spawns a claude CLI process; if it doesn't exit
        # cleanly (crash, timeout, or Bun.js hang), it accumulates
        # memory.  Kill orphans now rather than at session end.
        _terminate_child_processes()

        if response is None:
            # Esc was pressed — preserve message for editing
            console.print("\n[dim]Cancelled. Your message is preserved — edit or resend.[/dim]")
            _prefill = user_input
            continue

        if isinstance(response, str):
            # Error message
            err_msg = response
            if "exit code" in err_msg or "Fatal error" in err_msg:
                console.print("\n[yellow]The agent encountered an error processing this request.[/yellow]")
                if not verbose:
                    console.print("[dim]Try rephrasing your question or use --verbose for details.[/dim]")
            elif "budget exhausted" in err_msg.lower():
                console.print(
                    f"\n[bold yellow]Session budget exhausted (${max_cost:.2f}).[/bold yellow]\n"
                    "Start a new session to continue."
                )
                break
            else:
                console.print(f"\n[red]Error: {err_msg}[/red]")
            if verbose:
                console.print(f"\n[dim]{err_msg}[/dim]")
                _print_stderr_log()
            continue

        # Check if the response text contains an error (engine caught it)
        is_error_response = "encountered an error" in response.text and "Technical:" in response.text

        if is_error_response:
            console.print()
            console.print(Markdown(response.text), width=console.width - 2)
            if verbose:
                _print_stderr_log()
        else:
            # Render the complete response as markdown.
            # width - 2 prevents terminal hard-wrap when Rich miscalculates
            # the visual width of Unicode characters (em dashes, curly quotes).
            console.print()
            console.print(Markdown(response.text), width=console.width - 2)

        # Footer: tools, memory, cost
        footer_parts: list[str] = []
        if verbose and response.tools_used:
            footer_parts.append(f"Tools: {', '.join(response.tools_used)}")
        if response.memories_saved > 0:
            label = "memory" if response.memories_saved == 1 else "memories"
            footer_parts.append(f"{response.memories_saved} {label} saved")
        footer_parts.append(
            f"Turn {response.turn_number} | ${response.estimated_cost:.4f} | ${response.session_cost:.4f} total"
        )
        console.print(f"[dim]{'  ·  '.join(footer_parts)}[/dim]")
        console.rule(style="dim")

    # Finalize session (save transcript, fallback summarization)
    try:
        asyncio.run(engine.close())
    except Exception as exc:
        if verbose:
            console.print(f"[dim]Session close warning: {exc}[/dim]")

    _terminate_child_processes()


# ---------------------------------------------------------------------------
# portfolio command group (Issue #118)
# ---------------------------------------------------------------------------


@main.group()
def portfolio() -> None:
    """Manage multiple deal projects and cross-deal analytics."""


@portfolio.command("add")
@click.argument("name", metavar="NAME")
@click.option(
    "--data-room",
    "data_room",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    required=True,
    help="Path to the project data room directory.",
)
@click.option("--deal-type", "deal_type", default="", help="Type of deal (e.g. acquisition, merger).")
@click.option("--buyer", default="", help="Name of the acquiring company.")
@click.option("--target", default="", help="Name of the target company.")
def portfolio_add(name: str, data_room: Path, deal_type: str, buyer: str, target: str) -> None:
    """Register a new deal project in the portfolio."""
    from dd_agents.persistence.project_registry import ProjectRegistryManager

    mgr = ProjectRegistryManager()
    try:
        entry = mgr.add_project(name, data_room, deal_type=deal_type, buyer=buyer, target=target)
        console.print(f"[green]Added project:[/green] {entry.name} ({entry.slug})")
        console.print(f"  Path: {entry.path}")
    except ValueError as exc:
        _print_error("Portfolio Error", str(exc))
        raise SystemExit(1) from exc


@portfolio.command("list")
def portfolio_list() -> None:
    """List all registered deal projects."""
    from dd_agents.persistence.project_registry import ProjectRegistryManager

    mgr = ProjectRegistryManager()
    projects = mgr.list_projects()
    if not projects:
        console.print("[dim]No projects registered. Use 'dd-agents portfolio add' to register one.[/dim]")
        return

    table = Table(title="Deal Portfolio", show_header=True)
    table.add_column("Name", style="bold")
    table.add_column("Status", width=12)
    table.add_column("Type", width=14)
    table.add_column("Subjects", justify="right")
    table.add_column("Findings", justify="right")
    table.add_column("Risk", justify="right")
    table.add_column("Last Run")

    for p in projects:
        status_color = {"completed": "green", "running": "cyan", "failed": "red", "archived": "dim"}.get(
            p.status, "white"
        )
        table.add_row(
            p.name,
            f"[{status_color}]{p.status}[/{status_color}]",
            p.deal_type or "-",
            str(p.total_subjects) if p.total_subjects else "-",
            str(p.total_findings) if p.total_findings else "-",
            f"{p.risk_score:.0f}" if p.risk_score else "-",
            p.last_run_at or "-",
        )
    console.print(table)


@portfolio.command("compare")
@click.argument("slugs", nargs=-1, metavar="[SLUGS]...")
def portfolio_compare(slugs: tuple[str, ...]) -> None:
    """Compare risk profiles across deals."""
    from dd_agents.persistence.project_registry import ProjectRegistryManager

    mgr = ProjectRegistryManager()
    comp = mgr.compare_projects(slugs=list(slugs) if slugs else None)

    if not comp.projects:
        console.print("[dim]No projects to compare.[/dim]")
        return

    console.print(
        Panel(
            f"[bold]Portfolio Overview[/bold]\n"
            f"Projects: {len(comp.projects)}\n"
            f"Total findings: {comp.total_findings}\n"
            f"Avg risk score: {comp.avg_risk_score:.1f}\n"
            f"Severity: {', '.join(f'{k}: {v}' for k, v in sorted(comp.severity_distribution.items()))}",
            border_style="blue",
        )
    )

    if comp.risk_benchmarks:
        console.print(
            f"[dim]Risk benchmarks: min={comp.risk_benchmarks.get('min', 0):.0f} "
            f"median={comp.risk_benchmarks.get('median', 0):.0f} "
            f"max={comp.risk_benchmarks.get('max', 0):.0f}[/dim]"
        )


@portfolio.command("remove")
@click.argument("slug", metavar="SLUG")
def portfolio_remove(slug: str) -> None:
    """Remove a project from the portfolio (does not delete deal data)."""
    from dd_agents.persistence.project_registry import ProjectRegistryManager

    mgr = ProjectRegistryManager()
    if mgr.remove_project(slug):
        console.print(f"[green]Removed project: {slug}[/green]")
    else:
        _print_error("Not Found", f"No project with slug '{slug}'")
        raise SystemExit(1)


# ---------------------------------------------------------------------------
# templates command group (Issue #123)
# ---------------------------------------------------------------------------


@main.group()
def templates() -> None:
    """Manage report templates and branding."""


@templates.command("list")
def templates_list() -> None:
    """List available report templates."""
    from dd_agents.reporting.templates import TemplateLibrary

    library = TemplateLibrary()
    for tpl in library.list_templates():
        console.print(f"[bold]{tpl.id}[/bold]: {tpl.name}")
        if tpl.description:
            console.print(f"  [dim]{tpl.description}[/dim]")


@templates.command("show")
@click.argument("template_id", metavar="TEMPLATE_ID")
def templates_show(template_id: str) -> None:
    """Show details of a specific template."""
    from dd_agents.reporting.templates import TemplateLibrary

    library = TemplateLibrary()
    tpl = library.get_template(template_id)
    if not tpl:
        _print_error("Not Found", f"Template '{template_id}' not found")
        raise SystemExit(1)

    console.print(f"[bold]{tpl.name}[/bold] ({tpl.id})")
    if tpl.description:
        console.print(f"[dim]{tpl.description}[/dim]")
    console.print(f"Detail level: {tpl.sections.detail_level}")
    if tpl.sections.include:
        console.print(f"Sections: {', '.join(tpl.sections.include)}")
    if tpl.branding.firm_name:
        console.print(f"Firm: {tpl.branding.firm_name}")


# ---------------------------------------------------------------------------
# knowledge log command (Issue #180)
# ---------------------------------------------------------------------------


@main.command("log")
@click.option(
    "--data-room",
    "data_room",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    required=True,
    help="Path to the data room folder.",
)
@click.option("--limit", type=int, default=20, show_default=True, help="Number of recent entries to show.")
@click.option(
    "--type", "interaction_type", default=None, help="Filter by type: pipeline_run, search, query, annotation."
)
def log_cmd(data_room: Path, limit: int, interaction_type: str | None) -> None:
    """Show the analysis chronicle — timeline of all interactions.

    \b
    Example:
        dd-agents log --data-room ./data_room
        dd-agents log --data-room ./data_room --limit 5 --type search
    """
    from dd_agents.knowledge.chronicle import AnalysisChronicle, InteractionType

    chronicle_path = data_room.resolve() / "_dd" / "forensic-dd" / "knowledge" / "chronicle.jsonl"
    chronicle = AnalysisChronicle(chronicle_path)

    if interaction_type:
        try:
            it = InteractionType(interaction_type)
        except ValueError:
            valid = ", ".join(t.value for t in InteractionType)
            _print_error("Invalid Type", f"'{interaction_type}' is not valid. Options: {valid}")
            raise SystemExit(1) from None
        entries = chronicle.read_by_type(it)[-limit:]
    else:
        entries = chronicle.read_recent(limit=limit)

    if not entries:
        console.print("[dim]No analysis history recorded yet.[/dim]")
        return

    table = Table(title="Analysis Chronicle", show_header=True)
    table.add_column("Timestamp", width=20)
    table.add_column("Type", width=22)
    table.add_column("Title")
    table.add_column("Entities", width=15)

    for entry in entries:
        ts = entry.timestamp[:19].replace("T", " ")
        entities = ", ".join(entry.entities_affected[:3])
        if len(entry.entities_affected) > 3:
            entities += f" +{len(entry.entities_affected) - 3}"
        table.add_row(ts, entry.interaction_type.value, entry.title, entities or "-")

    console.print(table)

    stats = chronicle.get_stats()
    console.print(f"\n[dim]Total entries: {stats['total_entries']}[/dim]")


# ---------------------------------------------------------------------------
# annotate command (Issue #182)
# ---------------------------------------------------------------------------


@main.command()
@click.option(
    "--data-room",
    "data_room",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    required=True,
    help="Path to the data room folder.",
)
@click.option("--entity", default=None, help="Entity safe_name to link this annotation to.")
@click.argument("note")
def annotate(data_room: Path, entity: str | None, note: str) -> None:
    """Add a user annotation to the knowledge base.

    \b
    Example:
        dd-agents annotate --data-room ./data_room "Key risk: vendor lock-in clause in Acme MSA"
        dd-agents annotate --data-room ./data_room --entity acme_corp "Needs legal review"
    """
    from dd_agents.knowledge._utils import now_iso
    from dd_agents.knowledge.base import DealKnowledgeBase
    from dd_agents.knowledge.filing import file_annotation

    kb = DealKnowledgeBase(data_room.resolve())
    kb.ensure_dirs()
    article_id = file_annotation(kb, note, entity, now_iso())
    console.print(f"[green]Annotation saved:[/green] {article_id}")
    if entity:
        console.print(f"  Linked to entity: {entity}")


# ---------------------------------------------------------------------------
# lineage command (Issue #183)
# ---------------------------------------------------------------------------


@main.command()
@click.option(
    "--data-room",
    "data_room",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    required=True,
    help="Path to the data room folder.",
)
@click.option("--entity", default=None, help="Filter to a specific entity safe_name.")
@click.option("--active-only", is_flag=True, default=False, help="Show only active findings.")
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["table", "json", "csv"], case_sensitive=False),
    default="table",
    show_default=True,
    help="Output format: table (rich), json, or csv.",
)
@click.option(
    "--output",
    "output_path",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="Write output to file instead of stdout.",
)
def lineage(
    data_room: Path,
    entity: str | None,
    active_only: bool,
    output_format: str,
    output_path: Path | None,
) -> None:
    """Show finding lineage — how findings evolve across runs.

    \b
    Example:
        dd-agents lineage --data-room ./data_room
        dd-agents lineage --data-room ./data_room --entity acme_corp --active-only
        dd-agents lineage --data-room ./data_room --format json --output lineage.json
        dd-agents lineage --data-room ./data_room --format csv --output lineage.csv
    """
    from dd_agents.knowledge.lineage import FindingLineageTracker

    lineage_path = data_room.resolve() / "_dd" / "forensic-dd" / "knowledge" / "lineage.json"
    tracker = FindingLineageTracker(lineage_path)
    tracker.load()

    if entity:
        findings = tracker.get_entity_lineage(entity)
    elif active_only:
        findings = tracker.get_active()
    else:
        findings = list(tracker._findings.values())

    if active_only and entity:
        findings = [f for f in findings if f.status.value == "active"]

    if not findings:
        console.print("[dim]No lineage data found.[/dim]")
        return

    sorted_findings = sorted(findings, key=lambda x: x.current_severity)

    if output_format == "json":
        records = [
            {
                "fingerprint": f.fingerprint,
                "entity": f.entity_safe_name,
                "severity": f.current_severity,
                "status": f.status.value,
                "title": f.latest_title,
                "category": f.category,
                "run_count": f.run_count,
                "first_seen": f.first_seen_run_id,
                "last_seen": f.last_seen_run_id,
                "severity_history": [
                    {
                        "run_id": h.run_id,
                        "old_severity": h.old_severity,
                        "new_severity": h.new_severity,
                        "timestamp": h.timestamp,
                    }
                    for h in f.severity_history
                ],
            }
            for f in sorted_findings
        ]
        json_text = json.dumps(records, indent=2)
        if output_path:
            output_path.write_text(json_text, encoding="utf-8")
            console.print(f"[green]Wrote {len(records)} findings to {output_path}[/green]")
        else:
            click.echo(json_text)
        return

    if output_format == "csv":
        import csv
        import io

        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(
            ["fingerprint", "entity", "severity", "status", "title", "category", "run_count", "first_seen", "last_seen"]
        )
        for f in sorted_findings:
            writer.writerow(
                [
                    f.fingerprint,
                    f.entity_safe_name,
                    f.current_severity,
                    f.status.value,
                    f.latest_title,
                    f.category,
                    f.run_count,
                    f.first_seen_run_id,
                    f.last_seen_run_id,
                ]
            )
        csv_text = buf.getvalue()
        if output_path:
            output_path.write_text(csv_text, encoding="utf-8")
            console.print(f"[green]Wrote {len(sorted_findings)} findings to {output_path}[/green]")
        else:
            click.echo(csv_text, nl=False)
        return

    # Default: rich table
    table = Table(title="Finding Lineage", show_header=True)
    table.add_column("Severity", width=8)
    table.add_column("Status", width=10)
    table.add_column("Entity", width=18)
    table.add_column("Title")
    table.add_column("Runs", justify="right", width=5)
    table.add_column("Category", width=20)

    for f in sorted_findings:
        sev_color = {SEVERITY_P0: "red", SEVERITY_P1: "bright_red", SEVERITY_P2: "yellow"}.get(
            f.current_severity, "white"
        )
        status_color = {"active": "green", "resolved": "dim", "recurred": "yellow"}.get(f.status.value, "white")
        table.add_row(
            f"[{sev_color}]{f.current_severity}[/{sev_color}]",
            f"[{status_color}]{f.status.value}[/{status_color}]",
            f.entity_safe_name,
            f.latest_title[:60],
            str(f.run_count),
            f.category,
        )

    console.print(table)
    console.print(f"\n[dim]Total tracked: {len(sorted_findings)}[/dim]")


# ---------------------------------------------------------------------------
# health command (Issue #185)
# ---------------------------------------------------------------------------


@main.command()
@click.option(
    "--data-room",
    "data_room",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    required=True,
    help="Path to the data room folder.",
)
@click.option("--auto-fix", is_flag=True, default=False, help="Auto-fix broken links and orphan articles.")
def health(data_room: Path, auto_fix: bool) -> None:
    """Run knowledge base health checks.

    \b
    Example:
        dd-agents health --data-room ./data_room
        dd-agents health --data-room ./data_room --auto-fix
    """
    from dd_agents.knowledge.base import DealKnowledgeBase
    from dd_agents.knowledge.health import KnowledgeHealthChecker

    project_dir = data_room.resolve()
    kb = DealKnowledgeBase(project_dir)

    if not kb.exists:
        console.print("[dim]No knowledge base found. Run the pipeline first.[/dim]")
        return

    checker = KnowledgeHealthChecker(kb, data_room_path=project_dir)
    result = checker.run_all_checks(auto_fix=auto_fix)

    # Summary
    status_color = "green" if result.total_issues == 0 else "yellow" if result.total_issues < 5 else "red"
    console.print(
        Panel(
            f"[bold {status_color}]Issues found: {result.total_issues}[/bold {status_color}]\n"
            f"Articles: {result.knowledge_base_stats.get('total', 0)}\n"
            f"Auto-fixed: {result.auto_fixed}",
            title="Knowledge Base Health",
            border_style=status_color,
        )
    )

    if result.issues:
        table = Table(show_header=True)
        table.add_column("Severity", width=8)
        table.add_column("Category", width=18)
        table.add_column("Description")
        table.add_column("Action")

        for issue in result.issues:
            sev_color = "red" if issue.severity == "error" else "yellow"
            table.add_row(
                f"[{sev_color}]{issue.severity}[/{sev_color}]",
                issue.category.value,
                issue.description[:80],
                issue.suggested_action[:60],
            )
        console.print(table)


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
                    has_db = bool(deal_config.model_dump().get("source_of_truth", {}).get("subject_database"))
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

"""Top-level orchestration for the ``dd-agents search`` command."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING

from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress

from dd_agents.models.search import SearchPrompts
from dd_agents.utils.constants import INDEX_DIR, TEXT_DIR

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)


class SearchRunner:
    """Orchestrate discovery, extraction, analysis, and report generation.

    Parameters
    ----------
    prompts_path:
        Path to the prompts JSON file.
    data_room_path:
        Root of the data room.
    output_path:
        Destination for the Excel report.
    group_filter:
        Comma-separated group names to include (case-insensitive partial match).
    customer_filter:
        Comma-separated customer names to include (case-insensitive partial match).
    concurrency:
        Maximum parallel API calls.
    auto_confirm:
        Skip cost confirmation prompt.
    verbose:
        Enable debug logging.
    """

    def __init__(
        self,
        prompts_path: Path,
        data_room_path: Path,
        output_path: Path | None = None,
        group_filter: str | None = None,
        customer_filter: str | None = None,
        concurrency: int = 5,
        auto_confirm: bool = False,
        verbose: bool = False,
    ) -> None:
        self._prompts_path = prompts_path
        self._data_room = data_room_path.resolve()
        self._group_filter = group_filter
        self._customer_filter = customer_filter
        self._concurrency = concurrency
        self._auto_confirm = auto_confirm
        self._verbose = verbose

        # Derive output path from prompts file name if not provided.
        if output_path is not None:
            self._output_path = output_path
        else:
            stem = prompts_path.stem
            self._output_path = self._data_room / f"search_{stem}.xlsx"

        self._console = Console()
        self._err_console = Console(stderr=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self) -> None:
        """Execute the full search workflow."""
        # 1. Load prompts.
        prompts = self._load_prompts()

        column_list = "\n".join(f"  {i + 1}. {col.name}" for i, col in enumerate(prompts.columns))
        self._console.print(
            Panel(
                f"[bold]{prompts.name}[/bold]\n"
                f"{prompts.description}\n\n"
                f"Questions ({len(prompts.columns)}):\n{column_list}",
                title="Search Prompts",
                border_style="cyan",
            )
        )

        # 2. Discover files and build customer registry.
        from dd_agents.inventory.customers import CustomerRegistryBuilder
        from dd_agents.inventory.discovery import FileDiscovery

        discovery = FileDiscovery()
        files = discovery.discover(self._data_room)

        builder = CustomerRegistryBuilder()
        customers, counts = builder.build(self._data_room, files)

        if not customers:
            self._err_console.print(
                Panel(
                    "[bold red]No customers found[/bold red]\n\n"
                    "The data room must follow this directory structure:\n\n"
                    "  data_room/\n"
                    "    GroupName/\n"
                    "      CustomerName/\n"
                    "        contract.pdf\n"
                    "        amendment.docx\n"
                    "        ...\n\n"
                    "Each customer must be in a subfolder under a group folder.",
                    title="Error",
                    border_style="red",
                )
            )
            raise SystemExit(1)

        # 3. Apply group filter, then customer filter.
        if self._group_filter:
            gfilters = [g.strip().lower() for g in self._group_filter.split(",") if g.strip()]
            customers = [c for c in customers if any(g in c.group.lower() for g in gfilters)]
            if not customers:
                self._err_console.print(
                    Panel(
                        f"[bold red]No customers matched group filter:[/bold red] {self._group_filter}",
                        title="Error",
                        border_style="red",
                    )
                )
                raise SystemExit(1)

        if self._customer_filter:
            filters = [f.strip().lower() for f in self._customer_filter.split(",") if f.strip()]
            customers = [c for c in customers if any(f in c.name.lower() for f in filters)]
            if not customers:
                self._err_console.print(
                    Panel(
                        f"[bold red]No customers matched filter:[/bold red] {self._customer_filter}",
                        title="Error",
                        border_style="red",
                    )
                )
                raise SystemExit(1)

        filtered_files = sum(c.file_count for c in customers)
        self._console.print(f"\nCustomers: {len(customers)} | Files: {filtered_files}")

        # 4. Ensure text extraction is complete for the filtered files.
        text_dir = self._data_room / TEXT_DIR
        cache_path = self._data_room / INDEX_DIR / "checksums.sha256"

        # Only extract files belonging to filtered customers.
        relevant_file_paths = [str(self._data_room / fp) for c in customers for fp in c.files]

        if relevant_file_paths:
            self._console.print("\n[bold]Running text extraction...[/bold]")
            from dd_agents.extraction.pipeline import ExtractionPipeline

            pipeline = ExtractionPipeline()
            pipeline.extract_all(
                files=relevant_file_paths,
                output_dir=text_dir,
                cache_path=cache_path,
            )
            self._console.print("[green]Extraction complete.[/green]")

        # 5. Cost estimate and confirmation.
        from dd_agents.search.analyzer import SearchAnalyzer

        analyzer = SearchAnalyzer(
            prompts=prompts,
            data_room_path=self._data_room,
            text_dir=text_dir,
            concurrency=self._concurrency,
        )

        estimate = analyzer.estimate_cost(customers)
        api_calls_info = f"~{estimate['total_api_calls']} API calls"
        if estimate.get("chunked_customers", 0) > 0:
            api_calls_info += f" ({estimate['chunked_customers']} customers chunked)"
        cost_lines = [
            f"Customers to analyse: {estimate['total_customers']}",
            f"Files with extracted text: {estimate['files_with_text']}",
            f"Estimated API calls: {api_calls_info}",
            f"Estimated API cost: [bold]${estimate['estimated_cost_usd']:.2f}[/bold]",
        ]
        if estimate["files_missing_text"] > 0:
            cost_lines.append(
                f"[bold yellow]Warning: {estimate['files_missing_text']} files have no extracted text "
                f"and will be skipped[/bold yellow]"
            )
        if self._verbose:
            cost_lines.append(f"  (input tokens: ~{estimate['estimated_input_tokens']:,})")
            cost_lines.append(f"  (output tokens: ~{estimate['estimated_output_tokens']:,})")
        self._console.print(
            Panel(
                "\n".join(cost_lines),
                title="Cost Estimate",
                border_style="yellow",
            )
        )

        if not self._auto_confirm:
            self._console.print()
            confirm = input("Type 'yes' to proceed, or press Enter to cancel: ").strip().lower()
            if confirm not in ("y", "yes"):
                self._console.print("[yellow]Cancelled.[/yellow]")
                return

        # 6. Run analysis with progress bar.
        from dd_agents.models.search import SearchCustomerResult

        analyzed: list[SearchCustomerResult] = []
        with Progress(console=self._console) as progress:
            task = progress.add_task("Analyzing customers...", total=len(customers))

            def on_progress(customer_name: str) -> None:
                progress.advance(task)

            analyzed = asyncio.run(analyzer.analyze_all(customers, progress_callback=on_progress))

        # 7. Verify completeness.
        if len(analyzed) != len(customers):
            self._err_console.print(
                Panel(
                    f"[bold red]COMPLETENESS WARNING:[/bold red] "
                    f"Expected {len(customers)} results, got {len(analyzed)}.\n"
                    "Some customers may be missing from the report.",
                    title="Warning",
                    border_style="red",
                )
            )
            logger.error(
                "COMPLETENESS VIOLATION: %d customers submitted, %d results returned",
                len(customers),
                len(analyzed),
            )

        # 8. Write Excel report.
        from dd_agents.search.excel_writer import SearchExcelWriter

        writer = SearchExcelWriter()
        writer.write(analyzed, prompts, self._output_path)

        # 9. Print summary with data quality metrics.
        failures = sum(1 for r in analyzed if r.error)
        incomplete = sum(1 for r in analyzed if r.incomplete_columns)
        skipped_files_total = sum(len(r.skipped_files) for r in analyzed)

        summary_lines = [
            "[bold green]Search complete[/bold green]",
            f"Customers analyzed: {len(analyzed)}",
        ]

        if failures:
            summary_lines.append(f"[bold red]Failures: {failures}[/bold red]")
        else:
            summary_lines.append("Failures: 0")

        if incomplete:
            summary_lines.append(f"[bold yellow]Incomplete responses: {incomplete}[/bold yellow]")

        if skipped_files_total:
            summary_lines.append(
                f"[bold yellow]Files skipped (no text extraction): {skipped_files_total}[/bold yellow]"
            )

        summary_lines.append(f"Output: {self._output_path}")

        self._console.print()
        self._console.print(
            Panel(
                "\n".join(summary_lines),
                title="Complete",
                border_style="green" if not failures else "yellow",
            )
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _load_prompts(self) -> SearchPrompts:
        """Load and validate the prompts file."""
        try:
            raw = self._prompts_path.read_text(encoding="utf-8")
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            self._err_console.print(
                Panel(
                    f"[bold red]Invalid JSON in prompts file:[/bold red]\n{exc}\n\n"
                    "The prompts file must be valid JSON. Example format:\n\n"
                    "  {{\n"
                    '    "name": "My Analysis",\n'
                    '    "columns": [\n'
                    "      {{\n"
                    '        "name": "Question Name",\n'
                    '        "prompt": "Your question here (at least 10 characters)"\n'
                    "      }}\n"
                    "    ]\n"
                    "  }}",
                    title="Error",
                    border_style="red",
                )
            )
            raise SystemExit(1) from exc

        try:
            return SearchPrompts.model_validate(data)
        except Exception as exc:
            self._err_console.print(
                Panel(
                    f"[bold red]Prompts file validation failed:[/bold red]\n{exc}\n\n"
                    "Required structure:\n"
                    '  - "name": string (1-200 characters)\n'
                    '  - "columns": array of 1-20 items, each with:\n'
                    '      "name": string (1-100 characters)\n'
                    '      "prompt": string (10-2000 characters)\n'
                    '  - "description": string (optional)\n\n'
                    "See examples/search/change_of_control.json for a working example.",
                    title="Error",
                    border_style="red",
                )
            )
            raise SystemExit(1) from exc

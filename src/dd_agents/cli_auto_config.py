"""Auto-config command logic: scan data room, analyze with Claude, generate deal-config.json."""

from __future__ import annotations

import json
import logging
import re
import subprocess
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from rich.table import Table

from dd_agents.cli_init import DEFAULT_FOCUS_AREAS, VALID_DEAL_TYPES

if TYPE_CHECKING:
    from pathlib import Path

    from rich.console import Console

logger = logging.getLogger(__name__)

# Directories/files to exclude from the tree output.
_TREE_EXCLUDE_PATTERN = (
    "__MACOSX|.DS_Store|_dd|_buyer|_batch*|_findings|_ocr*|_output|_product*|_scripts|_index|results|__pycache__"
)

_MAX_TREE_CHARS = 50_000

# Maximum characters of buyer document content to include in a single prompt.
_MAX_BUYER_DOC_CHARS = 80_000

# Maximum characters of SPA content to include in extraction prompt.
_MAX_SPA_CHARS = 60_000

# Valid risk tolerance values for buyer_strategy.
_VALID_RISK_TOLERANCES = {"conservative", "moderate", "aggressive"}


def get_tree_output(data_room_path: Path, max_depth: int = 4) -> str:
    """Return a directory tree string for *data_room_path*.

    Uses the ``tree`` CLI binary when available; falls back to a pure-Python
    ``os.walk`` implementation otherwise.  Output is truncated to
    ``_MAX_TREE_CHARS`` characters for very large data rooms.
    """
    tree_text = _tree_via_binary(data_room_path, max_depth)
    if tree_text is None:
        tree_text = _tree_via_walk(data_room_path, max_depth)

    if len(tree_text) > _MAX_TREE_CHARS:
        tree_text = tree_text[:_MAX_TREE_CHARS] + "\n... (truncated)"

    return tree_text


def _tree_via_binary(data_room_path: Path, max_depth: int) -> str | None:
    """Try to run the ``tree`` binary.  Returns *None* if not installed."""
    try:
        result = subprocess.run(
            [
                "tree",
                "-I",
                _TREE_EXCLUDE_PATTERN,
                "--dirsfirst",
                "-F",
                "-L",
                str(max_depth),
                str(data_room_path),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout
    except FileNotFoundError:
        logger.debug("tree binary not found; falling back to os.walk")
    except subprocess.TimeoutExpired:
        logger.warning("tree command timed out")
    return None


def _tree_via_walk(data_room_path: Path, max_depth: int) -> str:
    """Pure-Python fallback that mimics ``tree`` output."""
    # Set of directory base-names to skip (simplified from the glob pattern).
    skip_names = {
        "__MACOSX",
        ".DS_Store",
        "_dd",
        "_buyer",
        "_findings",
        "_index",
        "results",
        "__pycache__",
    }
    skip_prefixes = ("_batch", "_ocr", "_output", "_product", "_scripts")

    lines: list[str] = [str(data_room_path)]

    def _should_skip(name: str) -> bool:
        if name in skip_names:
            return True
        return any(name.startswith(p) for p in skip_prefixes)

    def _walk(directory: Path, prefix: str, depth: int) -> None:
        if depth > max_depth:
            return
        try:
            entries = sorted(directory.iterdir(), key=lambda e: (not e.is_dir(), e.name))
        except PermissionError:
            return
        entries = [e for e in entries if not _should_skip(e.name)]
        for i, entry in enumerate(entries):
            is_last = i == len(entries) - 1
            connector = "\u2514\u2500\u2500 " if is_last else "\u251c\u2500\u2500 "
            suffix = "/" if entry.is_dir() else ""
            lines.append(f"{prefix}{connector}{entry.name}{suffix}")
            if entry.is_dir():
                extension = "    " if is_last else "\u2502   "
                _walk(entry, prefix + extension, depth + 1)

    _walk(data_room_path, "", 1)
    return "\n".join(lines)


def build_reference_file_summary(
    data_room_path: Path,
    files: list[Any] | None = None,
) -> list[dict[str, Any]]:
    """Identify root-level reference files (not inside subject folders).

    Returns a list of ``{"filename": str, "size_kb": int}`` dicts.
    """
    result: list[dict[str, Any]] = []
    if not data_room_path.is_dir():
        return result

    for entry in sorted(data_room_path.iterdir()):
        if entry.is_file() and not entry.name.startswith("."):
            size_kb = max(1, entry.stat().st_size // 1024)
            result.append({"filename": entry.name, "size_kb": size_kb})

    return result


# ---------------------------------------------------------------------------
# Document ingestion
# ---------------------------------------------------------------------------

# File extensions that can be converted to markdown.
_CONVERTIBLE_EXTENSIONS = frozenset({".docx", ".doc", ".pdf", ".pptx", ".xlsx", ".rtf", ".html", ".htm"})


def _clean_markdown(text: str) -> str:
    """Remove common conversion artifacts from markdown output."""
    # Remove HTML comments
    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    # Remove pandoc markup tags like {.mark}
    text = re.sub(r"\{\.[\w-]+\}", "", text)
    # Fix escaped quotes
    text = text.replace("\\'", "'")
    # Remove stray bracket artifacts from pandoc list processing
    text = re.sub(r"\[\\$\]", "", text)
    # Collapse multiple blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def convert_document_to_markdown(filepath: Path) -> str:
    """Convert a document file to markdown text.

    Tries ``markitdown`` first, then ``pandoc`` as a system fallback.
    Returns the extracted text, or empty string on failure.
    """
    ext = filepath.suffix.lower()
    if ext not in _CONVERTIBLE_EXTENSIONS:
        # Try reading as plain text
        try:
            return filepath.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""

    # Try markitdown
    text = _convert_via_markitdown(filepath)
    if text:
        return _clean_markdown(text)

    # Try pandoc
    text = _convert_via_pandoc(filepath)
    if text:
        return _clean_markdown(text)

    # Last resort: direct read
    try:
        return filepath.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _convert_via_markitdown(filepath: Path) -> str:
    """Convert using markitdown library. Returns empty string on failure."""
    try:
        from markitdown import MarkItDown

        converter = MarkItDown()
        result = converter.convert(str(filepath))
        text = result.text_content if hasattr(result, "text_content") else ""
        if text and text.strip():
            logger.debug("markitdown converted %s (%d chars)", filepath.name, len(text))
            return text
    except ImportError:
        logger.debug("markitdown not installed, skipping")
    except Exception as exc:
        logger.debug("markitdown failed for %s: %s", filepath.name, exc)
    return ""


def _convert_via_pandoc(filepath: Path) -> str:
    """Convert using pandoc system binary. Returns empty string on failure."""
    try:
        result = subprocess.run(
            ["pandoc", str(filepath), "-t", "markdown", "--wrap=none"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode == 0 and result.stdout.strip():
            logger.debug("pandoc converted %s (%d chars)", filepath.name, len(result.stdout))
            return result.stdout
    except FileNotFoundError:
        logger.debug("pandoc not installed, skipping")
    except subprocess.TimeoutExpired:
        logger.warning("pandoc timed out for %s", filepath.name)
    except OSError as exc:
        logger.debug("pandoc failed for %s: %s", filepath.name, exc)
    return ""


@dataclass
class IngestedContext:
    """Results of buyer document ingestion."""

    buyer_doc_paths: list[Path] = field(default_factory=list)
    buyer_doc_contents: list[str] = field(default_factory=list)
    spa_content: str = ""
    press_release_content: str = ""
    buyer_docs_dir: str = "_buyer"


class BuyerContextIngester:
    """Convert and place buyer context documents in the data room."""

    def ingest(
        self,
        data_room_path: Path,
        buyer_docs: list[Path] | None = None,
        spa_path: Path | None = None,
        press_release_path: Path | None = None,
        buyer_docs_dir: str = "_buyer",
    ) -> IngestedContext:
        """Convert docs to markdown, place in data room, return content summaries.

        Buyer docs are converted and placed in ``{data_room}/{buyer_docs_dir}/``
        so agents can read them at runtime. SPA and press release content are
        extracted to memory only (not placed in data room for sensitivity reasons).
        """
        from pathlib import Path as PathCls

        ctx = IngestedContext(buyer_docs_dir=buyer_docs_dir)

        # Process buyer documents
        if buyer_docs:
            dest_dir = data_room_path / buyer_docs_dir
            dest_dir.mkdir(parents=True, exist_ok=True)

            for doc_path in buyer_docs:
                doc_path = PathCls(doc_path)
                if not doc_path.is_file():
                    logger.warning("Buyer doc not found: %s", doc_path)
                    continue

                text = convert_document_to_markdown(doc_path)
                if not text:
                    logger.warning("Failed to convert buyer doc: %s", doc_path.name)
                    continue

                # Write markdown to buyer docs directory
                md_name = doc_path.stem + ".md"
                md_path = dest_dir / md_name
                md_path.write_text(text, encoding="utf-8")
                ctx.buyer_doc_paths.append(md_path)
                ctx.buyer_doc_contents.append(text)
                logger.info("Converted buyer doc: %s -> %s", doc_path.name, md_path.name)

        # Extract SPA content (not placed in data room)
        if spa_path:
            spa_path_resolved = PathCls(spa_path)
            if spa_path_resolved.is_file():
                ctx.spa_content = convert_document_to_markdown(spa_path_resolved)
                if ctx.spa_content:
                    logger.info("Extracted SPA content: %d chars", len(ctx.spa_content))
                else:
                    logger.warning("Failed to extract SPA content from: %s", spa_path)
            else:
                logger.warning("SPA file not found: %s", spa_path)

        # Extract press release content (not placed in data room)
        if press_release_path:
            pr_path_resolved = PathCls(press_release_path)
            if pr_path_resolved.is_file():
                ctx.press_release_content = convert_document_to_markdown(pr_path_resolved)
                if ctx.press_release_content:
                    logger.info("Extracted press release content: %d chars", len(ctx.press_release_content))
                else:
                    logger.warning("Failed to extract press release from: %s", press_release_path)
            else:
                logger.warning("Press release file not found: %s", press_release_path)

        return ctx


# ---------------------------------------------------------------------------
# Data Room Analyzer
# ---------------------------------------------------------------------------


class DataRoomAnalyzer:
    """Analyze a data room using Claude to produce a complete deal-config."""

    def __init__(
        self,
        data_room_path: Path,
    ) -> None:
        self._data_room_path = data_room_path

    async def analyze(
        self,
        tree_output: str,
        scan_result: dict[str, Any],
        reference_files: list[dict[str, Any]],
        buyer: str,
        target: str,
        deal_type_hint: str | None = None,
        ingested_context: IngestedContext | None = None,
    ) -> dict[str, Any]:
        """Run multi-turn Claude analysis and return a config dict.

        Turn 1: Entity resolution from data room tree (always runs).
        Turn 2: Buyer strategy synthesis (runs when buyer docs or PR provided).
        Turn 3: SPA structure extraction (runs when SPA provided).
        """
        # Turn 1: Entity resolution (existing behavior)
        system_prompt = self._build_system_prompt(buyer, target)
        spa_hint = ""
        if ingested_context and ingested_context.spa_content:
            spa_hint = ingested_context.spa_content[:5000]
        user_prompt = self._build_user_prompt(
            tree_output,
            scan_result,
            reference_files,
            buyer,
            target,
            deal_type_hint,
            spa_entities=spa_hint,
        )
        raw_text = await self._call_claude(system_prompt, user_prompt)
        config = self._parse_response(raw_text)

        if ingested_context is None:
            return config

        # Turn 2: Buyer strategy synthesis
        has_buyer_content = bool(ingested_context.buyer_doc_contents or ingested_context.press_release_content)
        if has_buyer_content:
            strategy_prompt = self._build_buyer_strategy_prompt(
                buyer,
                target,
                config,
                ingested_context,
            )
            strategy_text = await self._call_claude(
                self._build_buyer_strategy_system_prompt(buyer, target),
                strategy_prompt,
            )
            strategy = self._parse_response(strategy_text)
            config["buyer_strategy"] = strategy.get("buyer_strategy", strategy)

        # Turn 3: SPA extraction
        if ingested_context.spa_content:
            spa_prompt = self._build_spa_extraction_prompt(
                buyer,
                target,
                config,
                ingested_context.spa_content,
            )
            spa_text = await self._call_claude(
                self._build_spa_system_prompt(),
                spa_prompt,
            )
            spa_data = self._parse_response(spa_text)
            self._merge_spa_into_config(config, spa_data)

        return config

    # ------------------------------------------------------------------
    # Turn 1: Entity Resolution Prompts
    # ------------------------------------------------------------------

    def _build_system_prompt(self, buyer: str, target: str) -> str:
        return (
            "You are a senior M&A due diligence analyst specializing in technology acquisitions.\n\n"
            f"You are analyzing a data room for a potential deal where **{buyer}** is the buyer "
            f"and **{target}** is the target company.\n\n"
            "## Your Task\n\n"
            "Given the buyer name, target name, data room directory structure, and file metadata, "
            "produce a complete deal configuration JSON object. You must:\n\n"
            "1. **Resolve official entities**: Find the full legal names, stock ticker/exchange "
            "(if public), corporate structure. E.g., 'Acme' -> 'Acme Corporation' (ACME, NYSE).\n"
            "2. **Discover org structure**: From reference file names and folder patterns, identify "
            "subsidiaries, parent entities, d.b.a. names. E.g., 'WidgetCo' -> WidgetCo Holdings LLC, "
            "WidgetCo Inc., Sprocket Technologies Inc. (d.b.a. GearHub).\n"
            "3. **Find historical names**: Look for clues in file names suggesting previous company "
            "names, rebranding history. E.g., folder names or files mentioning 'OldBrandName', 'PriorCo'.\n"
            "4. **Detect acquired entities**: Look for merged/acquired company references in file "
            "names and folder structure.\n"
            "5. **Generate entity name variants**: Produce ALL plausible contract-matching variants -- "
            "full legal, abbreviations, with/without Inc./Corp./Ltd./ULC, historical names, subsidiaries, "
            "d.b.a. names. Be comprehensive.\n"
            "6. **Choose focus areas**: Based on document types found (MSAs, DPAs, Order Forms, NDAs, "
            "SOWs, POs, amendments), pick the most relevant analysis areas from this list:\n"
            "   - change_of_control_clauses\n"
            "   - ip_ownership\n"
            "   - revenue_recognition\n"
            "   - customer_concentration\n"
            "   - auto_renewal_terms\n"
            "   - data_privacy_compliance\n"
            "   - liability_caps\n"
            "   - non_compete_agreements\n"
            "7. **Infer deal type**: From context clues (default to 'acquisition' if unclear). "
            f"Valid types: {', '.join(VALID_DEAL_TYPES)}. "
            "Use 'asset_sale' when the deal involves an Asset Purchase Agreement (APA) where "
            "specific assets are being purchased rather than shares/equity — common in "
            "receivership, bankruptcy, or distressed sales.\n"
            "8. **Write deal notes**: Summarize what the data room contains.\n\n"
            "## Output Format\n\n"
            "Return ONLY a raw JSON object (no markdown fences, no explanation, no preamble). "
            "The JSON must conform to this structure:\n\n"
            "{\n"
            '  "config_version": "1.0.0",\n'
            '  "buyer": {\n'
            '    "name": "<official legal name>",\n'
            '    "ticker": "<stock ticker or empty string>",\n'
            '    "exchange": "<exchange name or empty string>",\n'
            '    "notes": "<any relevant notes>"\n'
            "  },\n"
            '  "target": {\n'
            '    "name": "<official legal name>",\n'
            '    "subsidiaries": ["<subsidiary1>", ...],\n'
            '    "previous_names": [{"name": "<old name>", "period": "<date range>", "notes": ""}],\n'
            '    "acquired_entities": [{"name": "<entity>", "acquisition_date": "", "deal_type": "", '
            '"notes": ""}],\n'
            '    "entity_name_variants_for_contract_matching": ["<variant1>", "<variant2>", ...],\n'
            '    "notes": "<summary of target>"\n'
            "  },\n"
            '  "deal": {\n'
            '    "type": "<deal_type>",\n'
            '    "focus_areas": ["<area1>", "<area2>", ...],\n'
            '    "notes": "<summary of data room contents>"\n'
            "  },\n"
            '  "entity_aliases": {\n'
            '    "canonical_to_variants": {"<canonical>": ["<variant1>", ...]}\n'
            "  }\n"
            "}\n\n"
            "IMPORTANT: Every field above is required. entity_name_variants_for_contract_matching "
            "must contain at least the target name. focus_areas must have at least one entry.\n\n"
            "Do NOT use any tools. Do NOT attempt to read files or browse the filesystem. "
            "All the information you need is provided in the user message below. "
            "Respond with ONLY the JSON object."
        )

    def _build_user_prompt(
        self,
        tree_output: str,
        scan_result: dict[str, Any],
        reference_files: list[dict[str, Any]],
        buyer: str,
        target: str,
        deal_type_hint: str | None = None,
        spa_entities: str = "",
    ) -> str:
        subject_names = scan_result.get("subject_names", [])
        groups = scan_result.get("groups", [])
        file_count = scan_result.get("file_count", 0)
        counts = scan_result.get("counts")

        parts: list[str] = [
            f"## Buyer\n{buyer}\n",
            f"## Target\n{target}\n",
        ]

        if deal_type_hint:
            parts.append(f"## Deal Type (user-specified)\n{deal_type_hint}\n")

        parts.append(f"## Data Room Directory Tree (depth 4)\n```\n{tree_output}\n```\n")

        # Statistics
        stats_lines = [
            f"- Total files: {file_count}",
            f"- Groups: {len(groups)} ({', '.join(groups[:20])})",
            f"- Subjects: {len(subject_names)}",
        ]
        if counts is not None:
            counts_dict = counts.model_dump() if hasattr(counts, "model_dump") else {}
            by_ext = counts_dict.get("by_extension", {})
            if by_ext:
                ext_summary = ", ".join(f"{k}: {v}" for k, v in sorted(by_ext.items()))
                stats_lines.append(f"- Files by extension: {ext_summary}")
        parts.append("## Statistics\n" + "\n".join(stats_lines) + "\n")

        # Reference files
        if reference_files:
            ref_lines = [f"- {rf['filename']} ({rf['size_kb']} KB)" for rf in reference_files]
            parts.append("## Reference Files (root-level)\n" + "\n".join(ref_lines) + "\n")

        # Subject folder names (first 100)
        if subject_names:
            display = subject_names[:100]
            suffix = f"\n... and {len(subject_names) - 100} more" if len(subject_names) > 100 else ""
            parts.append("## Subject Folder Names (first 100)\n" + ", ".join(display) + suffix + "\n")

        # SPA entity hints (if available)
        if spa_entities:
            parts.append(
                "## SPA Entity Hints (from deal document)\n"
                "The following excerpt from the SPA may contain entity names, "
                "holding companies, and share structures. Use these to improve "
                "entity resolution.\n\n"
                f"{spa_entities[:5000]}\n"
            )

        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Turn 2: Buyer Strategy Prompts
    # ------------------------------------------------------------------

    def _build_buyer_strategy_system_prompt(self, buyer: str, target: str) -> str:
        return (
            "You are a senior M&A strategist synthesizing buyer context documents "
            "into a structured acquisition strategy.\n\n"
            f"**Buyer**: {buyer}\n"
            f"**Target**: {target}\n\n"
            "## Rules\n\n"
            "- Every synergy and risk must cite specific capabilities from the buyer documents.\n"
            "- Do NOT use generic boilerplate like 'technology synergies'. Be specific about "
            "named products, markets, and capabilities.\n"
            "- Frame risks as 'what matters to THIS buyer' not 'generic DD concerns'.\n"
            "- The `notes` field must include explicit file path references directing the "
            "Acquirer Intelligence Agent to read buyer context files.\n\n"
            "## Output Format\n\n"
            "Return ONLY a raw JSON object with a single key `buyer_strategy` containing:\n\n"
            "{\n"
            '  "buyer_strategy": {\n'
            '    "thesis": "<1-3 paragraph strategic rationale>",\n'
            '    "key_synergies": ["<specific synergy 1>", ...],\n'
            '    "integration_priorities": ["<priority 1>", ...],\n'
            '    "risk_tolerance": "conservative|moderate|aggressive",\n'
            '    "focus_areas": ["<buyer-specific risk area 1>", ...],\n'
            '    "budget_range": "<deal economics if known, else empty string>",\n'
            '    "notes": "<strategic context and file references for agents>"\n'
            "  }\n"
            "}\n\n"
            "IMPORTANT: Do NOT use any tools. All information you need is provided "
            "in the user message. Respond with ONLY the JSON object."
        )

    def _build_buyer_strategy_prompt(
        self,
        buyer: str,
        target: str,
        base_config: dict[str, Any],
        ctx: IngestedContext,
    ) -> str:
        parts: list[str] = []

        # Include base config context
        target_info = base_config.get("target", {})
        deal_info = base_config.get("deal", {})
        parts.append(
            f"## Deal Context\n"
            f"- Buyer: {buyer}\n"
            f"- Target: {target_info.get('name', target)}\n"
            f"- Deal type: {deal_info.get('type', 'acquisition')}\n"
            f"- DD focus areas: {', '.join(deal_info.get('focus_areas', []))}\n"
        )

        # Buyer documents
        if ctx.buyer_doc_contents:
            combined = "\n\n---\n\n".join(ctx.buyer_doc_contents)
            if len(combined) > _MAX_BUYER_DOC_CHARS:
                combined = combined[:_MAX_BUYER_DOC_CHARS] + "\n... (truncated)"
            parts.append(f"## Buyer Business Documents\n\n{combined}\n")

        # Buyer doc file paths for agent references
        if ctx.buyer_doc_paths:
            path_list = "\n".join(f"- {ctx.buyer_docs_dir}/{p.name}" for p in ctx.buyer_doc_paths)
            parts.append(
                f"## Buyer Document Paths in Data Room\n"
                f"Include these paths in the notes field so the Acquirer Intelligence Agent "
                f"can read them:\n{path_list}\n"
            )

        # Press release
        if ctx.press_release_content:
            pr_text = ctx.press_release_content
            if len(pr_text) > 10_000:
                pr_text = pr_text[:10_000] + "\n... (truncated)"
            parts.append(f"## Acquisition Press Release\n\n{pr_text}\n")

        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Turn 3: SPA Extraction Prompts
    # ------------------------------------------------------------------

    def _build_spa_system_prompt(self) -> str:
        return (
            "You are a senior M&A lawyer extracting structured deal terms from a Share Purchase Agreement (SPA).\n\n"
            "## Your Task\n\n"
            "Extract the following from the SPA text:\n"
            "1. **Purchase price** and structure (cash, stock, earnout)\n"
            "2. **Payment waterfall** mechanics (debt repayment, expenses, escrow)\n"
            "3. **Escrow terms** and holdback periods\n"
            "4. **Non-compete/restricted periods**\n"
            "5. **Closing conditions** and regulatory requirements\n"
            "6. **Entity structure** (holding companies, share classes, acquisition vehicles)\n"
            "7. **Material defined terms** (Business definition, key products)\n"
            "8. **Knowledge holders** (named individuals with disclosure obligations)\n\n"
            "## Output Format\n\n"
            "Return ONLY a raw JSON object:\n\n"
            "{\n"
            '  "budget_range": "<purchase price and payment waterfall summary>",\n'
            '  "spa_notes": "<entity structure, non-compete, closing conditions, key defined terms>",\n'
            '  "additional_entity_variants": ["<entity1>", "<entity2>"],\n'
            '  "key_executives": [{"name": "<name>", "title": "<title>", "company": "<company>"}]\n'
            "}\n\n"
            "IMPORTANT: Do NOT use any tools. All information you need is provided "
            "in the user message. Respond with ONLY the JSON object."
        )

    def _build_spa_extraction_prompt(
        self,
        buyer: str,
        target: str,
        base_config: dict[str, Any],
        spa_content: str,
    ) -> str:
        spa_text = spa_content
        if len(spa_text) > _MAX_SPA_CHARS:
            spa_text = spa_text[:_MAX_SPA_CHARS] + "\n... (truncated)"

        return (
            f"## Parties\n"
            f"- Buyer: {buyer}\n"
            f"- Target: {base_config.get('target', {}).get('name', target)}\n\n"
            f"## SPA Text\n\n{spa_text}\n"
        )

    def _merge_spa_into_config(
        self,
        config: dict[str, Any],
        spa_data: dict[str, Any],
    ) -> None:
        """Merge SPA extraction results into the config dict."""
        # Merge budget_range into buyer_strategy
        if "buyer_strategy" not in config:
            config["buyer_strategy"] = {}
        bs = config["buyer_strategy"]

        budget = spa_data.get("budget_range", "")
        if budget:
            existing = bs.get("budget_range", "")
            bs["budget_range"] = f"{existing} {budget}".strip() if existing else budget

        # Merge SPA notes
        spa_notes = spa_data.get("spa_notes", "")
        if spa_notes:
            existing_notes = bs.get("notes", "")
            separator = "\n\nSPA STRUCTURE: " if existing_notes else "SPA STRUCTURE: "
            bs["notes"] = f"{existing_notes}{separator}{spa_notes}" if existing_notes else f"SPA STRUCTURE: {spa_notes}"

        # Add entity variants from SPA
        additional_variants = spa_data.get("additional_entity_variants", [])
        if additional_variants and isinstance(additional_variants, list):
            target = config.setdefault("target", {})
            existing_variants = target.setdefault("entity_name_variants_for_contract_matching", [])
            for variant in additional_variants:
                if isinstance(variant, str) and variant not in existing_variants:
                    existing_variants.append(variant)

        # Add key executives
        key_execs = spa_data.get("key_executives", [])
        if key_execs and isinstance(key_execs, list):
            if "key_executives" not in config:
                config["key_executives"] = []
            existing_names = {e.get("name", "") for e in config["key_executives"] if isinstance(e, dict)}
            for exec_item in key_execs:
                if isinstance(exec_item, dict) and exec_item.get("name") not in existing_names:
                    exec_item.setdefault("title", "")
                    exec_item.setdefault("company", "")
                    exec_item.setdefault("notes", "")
                    config["key_executives"].append(exec_item)

    # ------------------------------------------------------------------
    # Claude API call
    # ------------------------------------------------------------------

    async def _call_claude(self, system_prompt: str, user_prompt: str) -> str:
        """Send a prompt to Claude via the Agent SDK and return the text response.

        The SDK respects the same environment configuration as Claude Code
        (``CLAUDE_CODE_USE_BEDROCK``, AWS credentials, etc.), so no
        API keys need to be managed by this code.

        Isolated as a method for testability.
        """
        from claude_agent_sdk import (
            AssistantMessage,
            ClaudeAgentOptions,
            ResultMessage,
            TextBlock,
            query,
        )

        logger.debug(
            "Calling Claude: system_prompt=%d chars, user_prompt=%d chars",
            len(system_prompt),
            len(user_prompt),
        )

        options = ClaudeAgentOptions(
            system_prompt=system_prompt,
            max_turns=3,
            permission_mode="bypassPermissions",
        )

        text_parts: list[str] = []
        async for message in query(prompt=user_prompt, options=options):
            logger.debug("SDK message: %s", type(message).__name__)
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    logger.debug("  block: %s", type(block).__name__)
                    if isinstance(block, TextBlock):
                        text_parts.append(block.text)
            elif isinstance(message, ResultMessage):
                logger.debug(
                    "  ResultMessage: is_error=%s, result=%s",
                    message.is_error,
                    getattr(message, "result", "N/A"),
                )
                if message.is_error:
                    # If we already captured text, use it despite the error
                    # (model may have emitted JSON before attempting a tool).
                    if text_parts:
                        logger.warning("Claude returned error but text was captured; using partial response")
                        break
                    raise RuntimeError(f"Claude returned error: {message.result}")

        result = "\n".join(text_parts)
        logger.debug("Claude response: %d chars", len(result))
        return result

    # ------------------------------------------------------------------
    # Response parsing
    # ------------------------------------------------------------------

    def _parse_response(self, raw_text: str) -> dict[str, Any]:
        """Parse Claude's JSON response, stripping markdown fences if present."""
        cleaned = raw_text.strip()

        # Strip markdown code fences
        if cleaned.startswith("```"):
            first_newline = cleaned.index("\n")
            cleaned = cleaned[first_newline + 1 :]
        if cleaned.endswith("```"):
            cleaned = cleaned[: cleaned.rfind("```")]
        # If there's a closing ``` in the middle (JSON followed by prose),
        # take only the content before it.
        elif "```" in cleaned:
            cleaned = cleaned[: cleaned.index("```")]
        cleaned = cleaned.strip()

        if not cleaned:
            raise ValueError("Claude returned an empty response")

        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError:
            # The model may have appended prose after the JSON object.
            # Try to find the outermost balanced braces.
            start = cleaned.find("{")
            if start == -1:
                raise ValueError("No JSON object found in Claude response")  # noqa: B904
            depth, end = 0, -1
            in_string, escape_next = False, False
            for i in range(start, len(cleaned)):
                ch = cleaned[i]
                if escape_next:
                    escape_next = False
                    continue
                if ch == "\\":
                    escape_next = True
                    continue
                if ch == '"' and not escape_next:
                    in_string = not in_string
                    continue
                if in_string:
                    continue
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        end = i
                        break
            if end == -1:
                raise ValueError("No complete JSON object found in Claude response")  # noqa: B904
            try:
                data = json.loads(cleaned[start : end + 1])
            except json.JSONDecodeError as exc2:
                raise ValueError(f"Failed to parse Claude response as JSON: {exc2}") from exc2

        if not isinstance(data, dict):
            raise ValueError(f"Expected a JSON object, got {type(data).__name__}")

        return data


# ---------------------------------------------------------------------------
# Interactive refinement
# ---------------------------------------------------------------------------


def run_interactive_refinement(
    config: dict[str, Any],
    console: Console,
) -> dict[str, Any]:
    """Interactively refine buyer_strategy with user input.

    Prompts the user to review and adjust the generated buyer strategy.
    Mutates and returns *config*.
    """
    bs = config.get("buyer_strategy")
    if not bs or not isinstance(bs, dict):
        return config

    console.print("\n[bold]Buyer Strategy Review[/bold]\n")

    # Show thesis
    thesis = bs.get("thesis", "")
    if thesis:
        console.print(f"[bold cyan]Thesis:[/bold cyan] {thesis[:500]}")
        response = _prompt_user("Accept thesis? [Y/edit] ", default="Y")
        if response.lower() not in ("y", "yes", ""):
            new_thesis = _prompt_user("Enter new thesis: ")
            if new_thesis:
                bs["thesis"] = new_thesis

    # Risk tolerance
    current_risk = bs.get("risk_tolerance", "moderate")
    console.print(f"\n[bold cyan]Risk tolerance:[/bold cyan] {current_risk}")
    response = _prompt_user(
        "Risk tolerance [conservative/moderate/aggressive] ",
        default=current_risk,
    )
    if response in _VALID_RISK_TOLERANCES:
        bs["risk_tolerance"] = response

    # Additional focus areas
    console.print(f"\n[bold cyan]Focus areas:[/bold cyan] {', '.join(bs.get('focus_areas', []))}")
    response = _prompt_user("Additional focus areas (comma-separated, or Enter to skip): ")
    if response.strip():
        additional = [a.strip() for a in response.split(",") if a.strip()]
        bs.setdefault("focus_areas", []).extend(additional)

    # Additional integration priorities
    console.print(
        f"\n[bold cyan]Integration priorities:[/bold cyan] {', '.join(bs.get('integration_priorities', [])[:5])}"
    )
    response = _prompt_user("Additional integration priorities (comma-separated, or Enter to skip): ")
    if response.strip():
        additional = [a.strip() for a in response.split(",") if a.strip()]
        bs.setdefault("integration_priorities", []).extend(additional)

    config["buyer_strategy"] = bs
    console.print("\n[green]Buyer strategy updated.[/green]")
    return config


def _prompt_user(prompt: str, default: str = "") -> str:
    """Prompt user for input with a default value."""
    try:
        response = input(prompt)
        return response if response else default
    except (EOFError, KeyboardInterrupt):
        return default


# ---------------------------------------------------------------------------
# Validation and summary
# ---------------------------------------------------------------------------


def validate_and_fix_config(
    config: dict[str, Any],
    scan_result: dict[str, Any],
) -> dict[str, Any]:
    """Fix common Claude mistakes before Pydantic validation.

    Mutates and returns *config*.
    """
    # config_version
    if not config.get("config_version"):
        config["config_version"] = "1.0.0"

    # buyer must exist
    if not config.get("buyer") or not isinstance(config["buyer"], dict):
        raise ValueError("Config is missing 'buyer' section")
    if not config["buyer"].get("name"):
        raise ValueError("Config buyer.name is empty")

    # target must exist
    if not config.get("target") or not isinstance(config["target"], dict):
        raise ValueError("Config is missing 'target' section")
    if not config["target"].get("name"):
        raise ValueError("Config target.name is empty")

    target_name = config["target"]["name"]

    # deal section
    if not config.get("deal") or not isinstance(config["deal"], dict):
        config["deal"] = {}

    deal = config["deal"]
    if not deal.get("type") or deal["type"] not in VALID_DEAL_TYPES:
        deal["type"] = "acquisition"

    if not deal.get("focus_areas") or not isinstance(deal["focus_areas"], list):
        deal["focus_areas"] = list(DEFAULT_FOCUS_AREAS[:4])

    # Inject deal-type-specific focus areas that agents need to see.
    if deal["type"] in ("asset_sale", "asset_purchase"):
        _asset_sale_areas = [
            "contract_assignability",
            "purchased_assets_schedule",
            "excluded_liabilities",
            "employee_transfer",
            "cure_costs",
        ]
        for area in _asset_sale_areas:
            if area not in deal["focus_areas"]:
                deal["focus_areas"].append(area)

    # Ensure entity_name_variants includes target name
    variants = config["target"].get("entity_name_variants_for_contract_matching")
    if not variants or not isinstance(variants, list):
        config["target"]["entity_name_variants_for_contract_matching"] = [target_name]
    elif target_name not in variants:
        config["target"]["entity_name_variants_for_contract_matching"].insert(0, target_name)

    # Ensure previous_names items have required fields
    prev_names = config["target"].get("previous_names", [])
    if isinstance(prev_names, list):
        for item in prev_names:
            if isinstance(item, dict):
                item.setdefault("period", "")
                item.setdefault("notes", "")

    # Ensure acquired_entities items have required fields
    acquired = config["target"].get("acquired_entities", [])
    if isinstance(acquired, list):
        for item in acquired:
            if isinstance(item, dict):
                item.setdefault("acquisition_date", "")
                item.setdefault("deal_type", "")
                item.setdefault("notes", "")

    # Merge subject folders names into entity_aliases.canonical_to_variants
    if not config.get("entity_aliases") or not isinstance(config["entity_aliases"], dict):
        config["entity_aliases"] = {}
    aliases = config["entity_aliases"]
    if "canonical_to_variants" not in aliases or not isinstance(aliases["canonical_to_variants"], dict):
        aliases["canonical_to_variants"] = {}

    subject_names = scan_result.get("subject_names", [])
    c2v = aliases["canonical_to_variants"]
    for folder_name in subject_names:
        clean_name = folder_name.replace("_", " ")
        if clean_name != folder_name:
            if clean_name not in c2v:
                c2v[clean_name] = [folder_name]
            elif folder_name not in c2v[clean_name]:
                c2v[clean_name].append(folder_name)

    # Fix buyer_strategy if present
    bs = config.get("buyer_strategy")
    if bs is not None and isinstance(bs, dict):
        # Ensure risk_tolerance is valid
        rt = bs.get("risk_tolerance", "")
        if rt not in _VALID_RISK_TOLERANCES:
            bs["risk_tolerance"] = "moderate"
        # Ensure all required fields exist with defaults
        bs.setdefault("thesis", "")
        bs.setdefault("key_synergies", [])
        bs.setdefault("integration_priorities", [])
        bs.setdefault("focus_areas", [])
        bs.setdefault("budget_range", "")
        bs.setdefault("notes", "")

    # Final Pydantic validation
    from dd_agents.config import validate_deal_config

    validate_deal_config(config)

    return config


def print_auto_config_summary(
    console: Console,
    config: dict[str, Any],
    scan_result: dict[str, Any],
) -> None:
    """Print a rich summary of the auto-generated config."""
    buyer = config.get("buyer", {})
    target = config.get("target", {})
    deal = config.get("deal", {})

    table = Table(title="Auto-Config Summary", show_header=False, padding=(0, 2))
    table.add_column("Field", style="bold cyan")
    table.add_column("Value")

    # Buyer info
    buyer_parts = [buyer.get("name", "")]
    ticker = buyer.get("ticker", "")
    exchange = buyer.get("exchange", "")
    if ticker:
        ticker_str = ticker
        if exchange:
            ticker_str += f" ({exchange})"
        buyer_parts.append(f"[{ticker_str}]")
    table.add_row("Buyer", " ".join(buyer_parts))

    # Target info
    table.add_row("Target", target.get("name", ""))

    subsidiaries = target.get("subsidiaries", [])
    if subsidiaries:
        table.add_row("Subsidiaries", ", ".join(subsidiaries))

    previous_names = target.get("previous_names", [])
    if previous_names:
        prev_strs = [p["name"] if isinstance(p, dict) else str(p) for p in previous_names]
        table.add_row("Previous Names", ", ".join(prev_strs))

    acquired = target.get("acquired_entities", [])
    if acquired:
        acq_strs = [a["name"] if isinstance(a, dict) else str(a) for a in acquired]
        table.add_row("Acquired Entities", ", ".join(acq_strs))

    variants = target.get("entity_name_variants_for_contract_matching", [])
    if variants:
        table.add_row("Entity Variants", ", ".join(variants[:15]))
        if len(variants) > 15:
            table.add_row("", f"... +{len(variants) - 15} more")

    # Deal info
    table.add_row("Deal Type", deal.get("type", ""))
    focus = deal.get("focus_areas", [])
    table.add_row("Focus Areas", ", ".join(focus))

    # Stats
    subject_count = len(scan_result.get("subject_names", []))
    file_count = scan_result.get("file_count", 0)
    table.add_row("Subjects", str(subject_count))
    table.add_row("Files", str(file_count))

    # Buyer strategy summary
    bs = config.get("buyer_strategy")
    if bs and isinstance(bs, dict):
        table.add_row("", "")  # spacer
        table.add_row("Buyer Strategy", "")
        thesis = bs.get("thesis", "")
        if thesis:
            table.add_row("  Thesis", thesis[:200] + ("..." if len(thesis) > 200 else ""))
        synergies = bs.get("key_synergies", [])
        if synergies:
            table.add_row("  Synergies", f"{len(synergies)} items")
        priorities = bs.get("integration_priorities", [])
        if priorities:
            table.add_row("  Integration", f"{len(priorities)} priorities")
        table.add_row("  Risk Tolerance", bs.get("risk_tolerance", "moderate"))
        bs_focus = bs.get("focus_areas", [])
        if bs_focus:
            table.add_row("  Buyer Focus", ", ".join(bs_focus[:5]))
        budget = bs.get("budget_range", "")
        if budget:
            table.add_row("  Budget", budget[:200])

    # Notes
    deal_notes = deal.get("notes", "")
    if deal_notes:
        table.add_row("Notes", deal_notes[:200])

    console.print(table)

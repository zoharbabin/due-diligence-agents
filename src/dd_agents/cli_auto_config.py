"""Auto-config command logic: scan data room, analyze with Claude, generate deal-config.json."""

from __future__ import annotations

import json
import logging
import subprocess
from typing import TYPE_CHECKING, Any

from rich.table import Table

from dd_agents.cli_init import DEFAULT_FOCUS_AREAS, VALID_DEAL_TYPES

if TYPE_CHECKING:
    from pathlib import Path

    from rich.console import Console

logger = logging.getLogger(__name__)

# Directories/files to exclude from the tree output.
_TREE_EXCLUDE_PATTERN = (
    "__MACOSX|.DS_Store|_dd|_batch*|_findings|_ocr*|_output|_product*|_scripts|_index|results|__pycache__"
)

_MAX_TREE_CHARS = 50_000


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
    """Identify root-level reference files (not inside customer folders).

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
    ) -> dict[str, Any]:
        """Run Claude analysis and return a config dict."""
        system_prompt = self._build_system_prompt(buyer, target)
        user_prompt = self._build_user_prompt(tree_output, scan_result, reference_files, buyer, target, deal_type_hint)
        raw_text = await self._call_claude(system_prompt, user_prompt)
        return self._parse_response(raw_text)

    # ------------------------------------------------------------------
    # Prompt building
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
            f"Valid types: {', '.join(VALID_DEAL_TYPES)}.\n"
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
            "must contain at least the target name. focus_areas must have at least one entry."
        )

    def _build_user_prompt(
        self,
        tree_output: str,
        scan_result: dict[str, Any],
        reference_files: list[dict[str, Any]],
        buyer: str,
        target: str,
        deal_type_hint: str | None = None,
    ) -> str:
        customer_names = scan_result.get("customer_names", [])
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
            f"- Customers: {len(customer_names)}",
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

        # Customer folder names (first 100)
        if customer_names:
            display = customer_names[:100]
            suffix = f"\n... and {len(customer_names) - 100} more" if len(customer_names) > 100 else ""
            parts.append("## Customer Folder Names (first 100)\n" + ", ".join(display) + suffix + "\n")

        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Claude API call (identical pattern to search/analyzer.py:254-287)
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

        options = ClaudeAgentOptions(
            system_prompt=system_prompt,
            max_turns=1,
            permission_mode="bypassPermissions",
        )

        text_parts: list[str] = []
        async for message in query(prompt=user_prompt, options=options):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        text_parts.append(block.text)
            elif isinstance(message, ResultMessage) and message.is_error:
                raise RuntimeError(f"Claude returned error: {message.result}")

        return "\n".join(text_parts)

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
        cleaned = cleaned.strip()

        if not cleaned:
            raise ValueError("Claude returned an empty response")

        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Failed to parse Claude response as JSON: {exc}") from exc

        if not isinstance(data, dict):
            raise ValueError(f"Expected a JSON object, got {type(data).__name__}")

        return data


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

    # Merge customer folder names into entity_aliases.canonical_to_variants
    if not config.get("entity_aliases") or not isinstance(config["entity_aliases"], dict):
        config["entity_aliases"] = {}
    aliases = config["entity_aliases"]
    if "canonical_to_variants" not in aliases or not isinstance(aliases["canonical_to_variants"], dict):
        aliases["canonical_to_variants"] = {}

    customer_names = scan_result.get("customer_names", [])
    c2v = aliases["canonical_to_variants"]
    for folder_name in customer_names:
        clean_name = folder_name.replace("_", " ")
        if clean_name != folder_name:
            if clean_name not in c2v:
                c2v[clean_name] = [folder_name]
            elif folder_name not in c2v[clean_name]:
                c2v[clean_name].append(folder_name)

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
    customer_count = len(scan_result.get("customer_names", []))
    file_count = scan_result.get("file_count", 0)
    table.add_row("Customers", str(customer_count))
    table.add_row("Files", str(file_count))

    # Notes
    deal_notes = deal.get("notes", "")
    if deal_notes:
        table.add_row("Notes", deal_notes[:200])

    console.print(table)

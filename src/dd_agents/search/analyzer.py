"""Core search engine: prompt building, Claude Agent SDK calls, response parsing.

Implements lessons from the Addleshaw Goddard RAG Report (2024):
- Provision-specific prompts directing the LLM toward exactly what to find
- Follow-up validation in the prompt ("pay special attention", "do not miss")
- Targeted system prompt that doesn't unduly increase context length
- Full audit trail of all files processed, skipped, and every column answered
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import TYPE_CHECKING, Any

from dd_agents.models.search import (
    SearchCitation,
    SearchColumnResult,
    SearchCustomerResult,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from dd_agents.models.inventory import CustomerEntry
    from dd_agents.models.search import SearchPrompts

logger = logging.getLogger(__name__)

# Approximate tokens per character for cost estimation.
_CHARS_PER_TOKEN = 4
_INPUT_COST_PER_MTOK = 3.0  # Claude Sonnet 4 pricing (USD per 1M tokens)
_OUTPUT_COST_PER_MTOK = 15.0

# Conservative prompt size limit (~150K tokens → 600K chars).  Leaves
# headroom for the system prompt and output tokens.
_MAX_PROMPT_CHARS = 600_000

# Error messages that indicate non-transient failures (don't retry).
_NON_TRANSIENT_ERRORS = ("Prompt is too long", "context length", "too many tokens")


class SearchAnalyzer:
    """Analyse customer contracts against custom prompts via the Claude Agent SDK.

    Uses ``claude_agent_sdk.query()`` to call Claude.  The SDK handles
    authentication and routing (Bedrock, Vertex, Anthropic API, etc.)
    based on the environment variables already configured for Claude Code.

    Parameters
    ----------
    prompts:
        Validated :class:`SearchPrompts` instance.
    data_room_path:
        Root of the data room.
    text_dir:
        Directory containing extracted ``.md`` text files.
    concurrency:
        Maximum parallel API calls.
    max_retries:
        Retries per customer on transient API errors.
    """

    def __init__(
        self,
        prompts: SearchPrompts,
        data_room_path: Path,
        text_dir: Path,
        concurrency: int = 5,
        max_retries: int = 3,
    ) -> None:
        self._prompts = prompts
        self._data_room = data_room_path
        self._text_dir = text_dir
        self._concurrency = concurrency
        self._max_retries = max_retries

    # ------------------------------------------------------------------
    # Cost estimation
    # ------------------------------------------------------------------

    def estimate_cost(self, customers: list[CustomerEntry]) -> dict[str, Any]:
        """Return a rough cost estimate for analysing *customers*.

        Returns
        -------
        dict
            Keys: ``total_customers``, ``total_files``, ``estimated_input_tokens``,
            ``estimated_output_tokens``, ``estimated_cost_usd``,
            ``files_with_text``, ``files_missing_text``.
        """
        total_chars = 0
        files_with_text = 0
        files_missing_text = 0
        system_chars = len(self._build_system_prompt())

        for customer in customers:
            customer_chars = system_chars
            for file_path in customer.files:
                text_path = self._get_text_path(file_path)
                if text_path.exists():
                    customer_chars += text_path.stat().st_size
                    files_with_text += 1
                else:
                    files_missing_text += 1
            total_chars += customer_chars

        estimated_input_tokens = total_chars // _CHARS_PER_TOKEN
        # Rough output estimate: ~500 tokens per column per customer.
        estimated_output_tokens = len(customers) * len(self._prompts.columns) * 500

        estimated_cost = (
            estimated_input_tokens / 1_000_000 * _INPUT_COST_PER_MTOK
            + estimated_output_tokens / 1_000_000 * _OUTPUT_COST_PER_MTOK
        )

        return {
            "total_customers": len(customers),
            "total_files": files_with_text + files_missing_text,
            "files_with_text": files_with_text,
            "files_missing_text": files_missing_text,
            "estimated_input_tokens": estimated_input_tokens,
            "estimated_output_tokens": estimated_output_tokens,
            "estimated_cost_usd": round(estimated_cost, 2),
        }

    # ------------------------------------------------------------------
    # Main analysis
    # ------------------------------------------------------------------

    async def analyze_all(
        self,
        customers: list[CustomerEntry],
        progress_callback: Callable[[str], None] | None = None,
    ) -> list[SearchCustomerResult]:
        """Analyse all *customers* concurrently.

        Every customer in the input list is guaranteed to appear in the
        output — errors are captured as :attr:`SearchCustomerResult.error`,
        never raised.

        Parameters
        ----------
        customers:
            Customer entries to analyse.
        progress_callback:
            Called with the customer name after each customer completes.

        Returns
        -------
        list[SearchCustomerResult]
        """
        semaphore = asyncio.Semaphore(self._concurrency)

        async def _bounded(customer: CustomerEntry) -> SearchCustomerResult:
            async with semaphore:
                try:
                    result = await self._analyze_customer(customer)
                except Exception as exc:
                    # Absolute safety net: no customer is ever lost.
                    logger.error("Unhandled exception for %s: %s", customer.name, exc)
                    result = SearchCustomerResult(
                        customer_name=customer.name,
                        group=customer.group,
                        total_files=customer.file_count,
                        error=f"Unexpected error: {exc}",
                    )
                if progress_callback is not None:
                    progress_callback(customer.name)
                return result

        tasks = [asyncio.create_task(_bounded(c)) for c in customers]
        results = list(await asyncio.gather(*tasks, return_exceptions=True))

        # Convert any stray exceptions into error results (belt and suspenders).
        final: list[SearchCustomerResult] = []
        for i, item in enumerate(results):
            if isinstance(item, BaseException):
                logger.error("gather() returned exception for customer %s: %s", customers[i].name, item)
                final.append(
                    SearchCustomerResult(
                        customer_name=customers[i].name,
                        group=customers[i].group,
                        total_files=customers[i].file_count,
                        error=f"Unexpected gather error: {item}",
                    )
                )
            else:
                final.append(item)

        # Verify completeness: every input customer must appear in output.
        if len(final) != len(customers):
            logger.error(
                "COMPLETENESS VIOLATION: %d customers in, %d results out",
                len(customers),
                len(final),
            )

        return final

    # ------------------------------------------------------------------
    # Per-customer analysis
    # ------------------------------------------------------------------

    async def _analyze_customer(self, customer: CustomerEntry) -> SearchCustomerResult:
        """Call the Claude Agent SDK for a single customer."""
        user_prompt, files_with_text, skipped_files = self._build_customer_prompt(customer)

        if not user_prompt:
            return SearchCustomerResult(
                customer_name=customer.name,
                group=customer.group,
                files_analyzed=0,
                total_files=customer.file_count,
                skipped_files=skipped_files,
                error="No extracted text found for this customer's files",
            )

        system_prompt = self._build_system_prompt()
        last_error: str = ""

        for attempt in range(1, self._max_retries + 1):
            try:
                raw_text = await self._call_claude(system_prompt, user_prompt)
            except Exception as exc:
                error_str = str(exc)
                is_non_transient = any(msg in error_str for msg in _NON_TRANSIENT_ERRORS)
                logger.warning(
                    "Attempt %d/%d failed for %s: %s%s",
                    attempt,
                    self._max_retries,
                    customer.name,
                    exc,
                    " (non-transient, skipping retries)" if is_non_transient else "",
                )
                if is_non_transient or attempt >= self._max_retries:
                    return SearchCustomerResult(
                        customer_name=customer.name,
                        group=customer.group,
                        files_analyzed=files_with_text,
                        total_files=customer.file_count,
                        skipped_files=skipped_files,
                        error=f"API error: {exc}",
                    )
                await asyncio.sleep(2**attempt)
                continue

            result = self._parse_response(raw_text, customer, files_with_text, skipped_files)

            # Accept if we got at least some parsed columns, even if
            # incomplete — partial data is better than retrying and
            # getting the same thing.
            if result.columns:
                return result

            # No columns at all (empty JSON, parse failure) — retry.
            last_error = result.error or "Unknown parse error"
            logger.warning(
                "Attempt %d/%d: unusable response for %s: %s",
                attempt,
                self._max_retries,
                customer.name,
                last_error,
            )
            if attempt < self._max_retries:
                await asyncio.sleep(2**attempt)

        # All retries exhausted with parse errors.
        return SearchCustomerResult(
            customer_name=customer.name,
            group=customer.group,
            files_analyzed=files_with_text,
            total_files=customer.file_count,
            skipped_files=skipped_files,
            error=last_error,
        )

    # ------------------------------------------------------------------
    # Claude Agent SDK call
    # ------------------------------------------------------------------

    async def _call_claude(self, system_prompt: str, user_prompt: str) -> str:
        """Send a prompt to Claude via the Agent SDK and return the text response.

        The SDK respects the same environment configuration as Claude Code
        (``CLAUDE_CODE_USE_BEDROCK``, AWS credentials, etc.), so no
        API keys need to be managed by this code.

        Isolated as a method for testability.

        Raises
        ------
        RuntimeError
            If the SDK returns an error or the response contains no text.
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
            disallowed_tools=["Read", "Edit", "Write", "Bash", "Glob", "Grep", "WebFetch", "Task", "NotebookEdit"],
        )

        text_parts: list[str] = []
        try:
            async for message in query(prompt=user_prompt, options=options):
                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, TextBlock):
                            text_parts.append(block.text)
                elif isinstance(message, ResultMessage) and message.is_error:
                    raise RuntimeError(f"Claude returned error: {message.result}")
        except RuntimeError as exc:
            if "cancel scope" in str(exc).lower():
                # Known SDK bug: cancel scope cleanup fails when the query
                # errored out.  The text_parts collected so far (if any) are
                # still usable, but if we have nothing, re-raise the original.
                logger.debug("Suppressed cancel-scope RuntimeError from SDK")
                if not text_parts:
                    raise
            else:
                raise

        result = "\n".join(text_parts)
        if not result.strip():
            raise RuntimeError("Claude returned an empty response (no TextBlock content)")
        return result

    # ------------------------------------------------------------------
    # Prompt building
    # ------------------------------------------------------------------

    def _build_system_prompt(self) -> str:
        """Build the system prompt with analysis instructions.

        Incorporates AG RAG Report lessons:
        - Provision-specific prompts for each question
        - Explicit completeness requirements ("answer ALL questions")
        - Follow-up validation language ("pay special attention", "do not miss")
        - Targeted instructions that don't unduly inflate context
        """
        column_descriptions = "\n".join(f"- **{col.name}**: {col.prompt}" for col in self._prompts.columns)

        column_names_list = ", ".join(f'"{col.name}"' for col in self._prompts.columns)

        return (
            "You are a meticulous legal due-diligence analyst reviewing customer contracts.\n\n"
            "## Critical Requirements\n\n"
            "You MUST answer EVERY question listed below. Do not skip any question.\n"
            f"Your JSON response MUST contain exactly these keys: {column_names_list}.\n"
            "If a question is not addressed in any document, you MUST still include the key "
            'with answer "NOT_ADDRESSED" — do NOT omit it.\n\n'
            "## Instructions\n\n"
            "1. Read EVERY document provided below in full. Do not skim or skip any section.\n"
            "2. Determine the document hierarchy by reading the precedence/supremacy clauses "
            "within the contracts themselves. Do NOT assume a fixed hierarchy. Common patterns:\n"
            "   - An MSA may state that order forms or SOWs supersede it on specific terms.\n"
            "   - An order form may state that it supersedes the MSA for conflicting provisions.\n"
            "   - Amendments supersede the documents they amend, but check effective dates.\n"
            "   - Look for 'order of precedence', 'conflict', 'prevail', or 'supersede' clauses.\n"
            "3. When provisions conflict between documents, apply the precedence rules found "
            "in the contracts to identify the controlling version. Cite the precedence clause.\n"
            "4. Cite every answer with: file_path, page (if identifiable), "
            "section_ref (e.g. 'Section 12.3'), and exact_quote (verbatim text from the document).\n"
            "5. If a question is not addressed in any document, answer 'NOT_ADDRESSED' "
            "with confidence 'HIGH' and an empty citations list.\n"
            "6. Provide multiple citations when a clause appears in more than one document.\n"
            "7. Pay special attention to schedules, exhibits, and annexes — "
            "relevant provisions are often buried in these sections.\n"
            "8. Double-check your work: re-read the questions and verify you have not "
            "missed any relevant clause in any document.\n\n"
            "## Questions to Answer\n\n"
            f"{column_descriptions}\n\n"
            "## Output Format\n\n"
            "Return ONLY raw JSON (no markdown fences, no explanation, no preamble). "
            f"You MUST include ALL {len(self._prompts.columns)} questions as top-level keys. "
            "Use exactly this structure:\n\n"
            "{\n"
            '  "<column_name>": {\n'
            '    "answer": "<YES|NO|NOT_ADDRESSED or free-text summary>",\n'
            '    "confidence": "<HIGH|MEDIUM|LOW>",\n'
            '    "citations": [\n'
            "      {\n"
            '        "file_path": "<source document path as shown in the Document header>",\n'
            '        "page": "<page number if identifiable, otherwise empty string>",\n'
            '        "section_ref": "<section reference, e.g. Section 12.3>",\n'
            '        "exact_quote": "<verbatim quote from the document>"\n'
            "      }\n"
            "    ]\n"
            "  }\n"
            "}\n"
        )

    def _build_customer_prompt(self, customer: CustomerEntry) -> tuple[str, int, list[str]]:
        """Build the user prompt containing all extracted document texts.

        Documents are included in order until the cumulative size
        approaches :data:`_MAX_PROMPT_CHARS`.  Any remaining files are
        reported as skipped so they still appear in the report metadata.

        Returns
        -------
        tuple[str, int, list[str]]
            The prompt text (empty string if no files found), the count
            of files that actually had extractable text, and a list of
            file paths that were skipped (missing or empty extraction).
        """
        header = f"# Customer: {customer.name} (Group: {customer.group})\n"
        parts: list[str] = [header]
        current_chars = len(header)
        files_found = 0
        skipped_files: list[str] = []

        for file_path in customer.files:
            text_path = self._get_text_path(file_path)
            if not text_path.exists():
                logger.warning("SKIPPED (no extraction): %s", file_path)
                skipped_files.append(file_path)
                continue

            text = text_path.read_text(encoding="utf-8", errors="replace")
            if not text.strip():
                logger.warning("SKIPPED (empty extraction): %s", file_path)
                skipped_files.append(file_path)
                continue

            doc_block = f"\n---\n## Document: {file_path}\n---\n{text}\n"
            if current_chars + len(doc_block) > _MAX_PROMPT_CHARS and files_found > 0:
                logger.warning(
                    "SKIPPED (prompt size limit): %s (%d chars would exceed %d limit)",
                    file_path,
                    current_chars + len(doc_block),
                    _MAX_PROMPT_CHARS,
                )
                skipped_files.append(file_path)
                continue

            parts.append(doc_block)
            current_chars += len(doc_block)
            files_found += 1

        if skipped_files:
            logger.warning(
                "Customer %s: %d of %d files skipped: %s",
                customer.name,
                len(skipped_files),
                customer.file_count,
                ", ".join(skipped_files),
            )

        if files_found == 0:
            return "", 0, skipped_files

        return "\n".join(parts), files_found, skipped_files

    # ------------------------------------------------------------------
    # Response parsing
    # ------------------------------------------------------------------

    def _parse_response(
        self,
        raw_text: str,
        customer: CustomerEntry,
        files_with_text: int,
        skipped_files: list[str],
    ) -> SearchCustomerResult:
        """Parse Claude's JSON response into a :class:`SearchCustomerResult`.

        Validates completeness: every expected column must be present in
        the response, and empty ``{}`` responses are rejected.
        """
        cleaned = self._extract_json_text(raw_text)

        if not cleaned:
            logger.error(
                "Empty response from Claude for %s (raw length: %d, preview: %.200s)",
                customer.name,
                len(raw_text),
                raw_text[:200],
            )
            return SearchCustomerResult(
                customer_name=customer.name,
                group=customer.group,
                files_analyzed=files_with_text,
                total_files=customer.file_count,
                skipped_files=skipped_files,
                error="Claude returned an empty response — no data extracted",
            )

        try:
            data: dict[str, Any] = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            logger.error(
                "JSON parse failed for %s: %s (preview: %.300s)",
                customer.name,
                exc,
                cleaned[:300],
            )
            return SearchCustomerResult(
                customer_name=customer.name,
                group=customer.group,
                files_analyzed=files_with_text,
                total_files=customer.file_count,
                skipped_files=skipped_files,
                error=f"Failed to parse API response as JSON: {exc}",
            )

        # Reject empty JSON object — Claude likely hit a context limit.
        if not data:
            logger.error("Claude returned empty JSON {} for %s", customer.name)
            return SearchCustomerResult(
                customer_name=customer.name,
                group=customer.group,
                files_analyzed=files_with_text,
                total_files=customer.file_count,
                skipped_files=skipped_files,
                error="Claude returned empty JSON {} — likely a context limit or model error",
            )

        # Parse columns and track which are missing.
        columns: dict[str, SearchColumnResult] = {}
        incomplete_columns: list[str] = []

        for col in self._prompts.columns:
            col_data = data.get(col.name)

            if col_data is None:
                # Column is completely missing from the response.
                logger.warning(
                    "INCOMPLETE RESPONSE for %s: missing column '%s'",
                    customer.name,
                    col.name,
                )
                incomplete_columns.append(col.name)
                columns[col.name] = SearchColumnResult(
                    answer="INCOMPLETE — not returned by model",
                    confidence="",
                    citations=[],
                )
                continue

            if not isinstance(col_data, dict):
                col_data = {"answer": str(col_data)}

            citations = []
            for cit in col_data.get("citations", []):
                if isinstance(cit, dict):
                    citations.append(
                        SearchCitation(
                            file_path=cit.get("file_path", ""),
                            page=str(cit.get("page", "")),
                            section_ref=cit.get("section_ref", ""),
                            exact_quote=cit.get("exact_quote", ""),
                        )
                    )

            columns[col.name] = SearchColumnResult(
                answer=col_data.get("answer", ""),
                confidence=col_data.get("confidence", ""),
                citations=citations,
            )

        error_msg = None
        if incomplete_columns:
            error_msg = f"Incomplete response — missing columns: {', '.join(incomplete_columns)}"

        return SearchCustomerResult(
            customer_name=customer.name,
            group=customer.group,
            files_analyzed=files_with_text,
            total_files=customer.file_count,
            skipped_files=skipped_files,
            columns=columns,
            incomplete_columns=incomplete_columns,
            error=error_msg,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_json_text(raw: str) -> str:
        """Best-effort extraction of a JSON object from *raw*.

        Handles:
        - Raw JSON (``{ ... }``)
        - Markdown fenced blocks (````json ... ``` ``)
        - Preamble text before the opening ``{``
        """
        cleaned = raw.strip()

        # Strip markdown code fences.
        if cleaned.startswith("```"):
            first_nl = cleaned.find("\n")
            if first_nl != -1:
                cleaned = cleaned[first_nl + 1 :]
        if cleaned.endswith("```"):
            cleaned = cleaned[: cleaned.rfind("```")]
        cleaned = cleaned.strip()

        # Already looks like JSON.
        if cleaned.startswith("{"):
            return cleaned

        # Try to find a top-level JSON object embedded in the text.
        match = re.search(r"\{", cleaned)
        if match:
            candidate = cleaned[match.start() :]
            # Quick sanity check: must end with }
            last_brace = candidate.rfind("}")
            if last_brace != -1:
                return candidate[: last_brace + 1]

        return cleaned

    def _get_text_path(self, source_path: str) -> Path:
        """Convert original file path to extracted text path.

        Resolves the relative *source_path* against the data room root
        so the safe filename matches what the extraction pipeline wrote
        (which receives absolute paths).
        """
        from dd_agents.extraction.pipeline import ExtractionPipeline

        absolute = str(self._data_room / source_path)
        safe_name = ExtractionPipeline._safe_text_name(absolute)
        return self._text_dir / safe_name

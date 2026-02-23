"""Core search engine: prompt building, Claude Agent SDK calls, response parsing.

Implements lessons from the Addleshaw Goddard RAG Report (2024):
- Provision-specific prompts directing the LLM toward exactly what to find
- Follow-up validation in the prompt ("pay special attention", "do not miss")
- Targeted system prompt that doesn't unduly increase context length
- Full audit trail of all files processed, skipped, and every column answered
- 4-phase analysis: map (per chunk) → merge → synthesis → validation
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING, Any

from dd_agents.models.search import (
    SearchCitation,
    SearchColumnResult,
    SearchCustomerResult,
)
from dd_agents.search.chunker import (
    TARGET_CHUNK_CHARS,
    AnalysisChunk,
    FileText,
    create_analysis_chunks,
    detect_page_markers,
    estimate_chunks,
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

# Error messages that indicate non-transient failures (don't retry).
_NON_TRANSIENT_ERRORS = ("Prompt is too long", "context length", "too many tokens")

# Document type inference from filename keywords.
_DOC_TYPE_KEYWORDS: dict[str, str] = {
    "msa": "MSA",
    "master": "MSA",
    "amendment": "Amendment",
    "sow": "SOW",
    "statement of work": "SOW",
    "order": "Order Form",
    "addendum": "Addendum",
    "renewal": "Renewal",
    "nda": "NDA",
    "side letter": "Side Letter",
    "exhibit": "Exhibit",
}


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
            ``files_with_text``, ``files_missing_text``,
            ``total_api_calls``, ``chunked_customers``.
        """
        total_chars = 0
        files_with_text = 0
        files_missing_text = 0
        total_api_calls = 0
        chunked_customers = 0
        system_chars = len(self._build_system_prompt())

        for customer in customers:
            customer_chars = system_chars
            file_sizes: list[int] = []
            for file_path in customer.files:
                text_path = self._get_text_path(file_path)
                if text_path.exists():
                    size = text_path.stat().st_size
                    customer_chars += size
                    file_sizes.append(size)
                    files_with_text += 1
                else:
                    files_missing_text += 1
            total_chars += customer_chars

            chunk_count = estimate_chunks(file_sizes, TARGET_CHUNK_CHARS)
            total_api_calls += chunk_count  # Phase 1: map calls
            if chunk_count > 1:
                chunked_customers += 1
                total_api_calls += 1  # Phase 3: synthesis pass
            total_api_calls += 1  # Phase 4: potential validation pass (worst case)

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
            "total_api_calls": total_api_calls,
            "chunked_customers": chunked_customers,
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
        # Suppress the SDK's cancel-scope RuntimeError that leaks from
        # internal background tasks.  Without this, asyncio's default
        # handler prints an ugly traceback we cannot catch with try/except.
        loop = asyncio.get_running_loop()
        _orig_handler = loop.get_exception_handler()

        def _quiet_handler(event_loop: asyncio.AbstractEventLoop, context: dict) -> None:  # type: ignore[type-arg]
            exc = context.get("exception")
            if isinstance(exc, RuntimeError) and "cancel scope" in str(exc).lower():
                logger.debug("Suppressed SDK cancel-scope error (background task)")
                return
            # Delegate everything else to the original handler or default.
            if _orig_handler is not None:
                _orig_handler(event_loop, context)
            else:
                event_loop.default_exception_handler(context)

        loop.set_exception_handler(_quiet_handler)

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

        # Restore original exception handler.
        loop.set_exception_handler(_orig_handler)

        return final

    # ------------------------------------------------------------------
    # Per-customer analysis (4-phase flow)
    # ------------------------------------------------------------------

    async def _analyze_customer(self, customer: CustomerEntry) -> SearchCustomerResult:
        """Analyse a single customer using the 4-phase chunked flow.

        Phase 1 — MAP:   Analyse each chunk independently.
        Phase 2 — MERGE: Mechanically combine chunk results.
        Phase 3 — SYNTH: Resolve conflicts via lightweight LLM call.
        Phase 4 — VALID: Re-query for remaining NOT_ADDRESSED answers.

        Single-chunk customers (the majority) skip Phases 2-3.
        """
        # I/O boundary: read extracted text files.
        file_texts, skipped_files = self._gather_file_texts(customer)

        if not file_texts:
            return SearchCustomerResult(
                customer_name=customer.name,
                group=customer.group,
                files_analyzed=0,
                total_files=customer.file_count,
                skipped_files=skipped_files,
                error="No extracted text found for this customer's files",
            )

        files_with_text = len(file_texts)

        # Create chunks (pure logic).
        chunks = create_analysis_chunks(file_texts, TARGET_CHUNK_CHARS)

        # PHASE 1: Map — analyse each chunk independently.
        chunk_results: list[SearchCustomerResult] = []
        for chunk in chunks:
            result = await self._analyze_single(chunk, customer, files_with_text, skipped_files)
            chunk_results.append(result)

        # PHASE 2: Merge.
        if len(chunk_results) == 1:
            merged = chunk_results[0]
            conflicted_columns: list[str] = []
        else:
            merged, conflicted_columns = self._merge_chunk_results(
                chunk_results, customer, files_with_text, skipped_files
            )

        # PHASE 3: Synthesis (multi-chunk with conflicts only).
        if conflicted_columns:
            merged = await self._synthesis_pass(merged, chunk_results, conflicted_columns, customer)

        # PHASE 4: Validation (NOT_ADDRESSED remaining).
        not_addressed = [
            col_name for col_name, col_result in merged.columns.items() if col_result.answer == "NOT_ADDRESSED"
        ]
        if not_addressed and file_texts:
            merged = await self._validation_pass(merged, file_texts, customer)

        merged.chunks_analyzed = len(chunks)
        return merged

    async def _analyze_single(
        self,
        chunk: AnalysisChunk,
        customer: CustomerEntry,
        files_with_text: int,
        skipped_files: list[str],
    ) -> SearchCustomerResult:
        """Run the retry loop for a single chunk. Returns a parsed result."""
        user_prompt = self._build_chunk_prompt(chunk, customer)
        system_prompt = self._build_system_prompt()
        last_error: str = ""

        for attempt in range(1, self._max_retries + 1):
            try:
                raw_text = await self._call_claude(system_prompt, user_prompt)
            except Exception as exc:
                error_str = str(exc)
                is_non_transient = any(msg in error_str for msg in _NON_TRANSIENT_ERRORS)
                logger.warning(
                    "Attempt %d/%d failed for %s (chunk %d/%d): %s%s",
                    attempt,
                    self._max_retries,
                    customer.name,
                    chunk.chunk_index + 1,
                    chunk.total_chunks,
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
            # incomplete — partial data is better than retrying.
            if result.columns:
                return result

            last_error = result.error or "Unknown parse error"
            logger.warning(
                "Attempt %d/%d: unusable response for %s (chunk %d/%d): %s",
                attempt,
                self._max_retries,
                customer.name,
                chunk.chunk_index + 1,
                chunk.total_chunks,
                last_error,
            )
            if attempt < self._max_retries:
                await asyncio.sleep(2**attempt)

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
            "4. Cite every answer with: file_path, page, "
            "section_ref (e.g. 'Section 12.3'), and exact_quote (verbatim text from the document).\n"
            "   Page numbers: PDF documents contain '--- Page N ---' markers. Use these to "
            "determine the exact page number for each citation. For non-PDF documents, use "
            "the page number from document footers if visible, otherwise leave page empty.\n"
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

    def _gather_file_texts(self, customer: CustomerEntry) -> tuple[list[FileText], list[str]]:
        """Read extracted ``.md`` files and return :class:`FileText` objects.

        This is the ONLY I/O point — everything downstream is pure logic.
        Files are skipped only for missing or empty extractions, NEVER for size.

        Returns
        -------
        tuple[list[FileText], list[str]]
            The file texts and a list of skipped file paths.
        """
        file_texts: list[FileText] = []
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

            file_texts.append(
                FileText(
                    file_path=file_path,
                    text=text,
                    has_page_markers=detect_page_markers(text),
                )
            )

        if skipped_files:
            logger.warning(
                "Customer %s: %d of %d files skipped (missing/empty extraction): %s",
                customer.name,
                len(skipped_files),
                customer.file_count,
                ", ".join(skipped_files),
            )

        return file_texts, skipped_files

    def _build_chunk_prompt(self, chunk: AnalysisChunk, customer: CustomerEntry) -> str:
        """Build the user prompt from an :class:`AnalysisChunk`.

        Single-chunk customers get the same format as the old
        ``_build_customer_prompt``.  Multi-chunk customers get a
        "Part X of Y" header instructing the LLM to answer NOT_ADDRESSED
        if the relevant information is not in this part.
        """
        header = f"# Customer: {customer.name} (Group: {customer.group})\n"
        parts: list[str] = [header]

        if chunk.total_chunks > 1:
            parts.append(
                f"\n**Analysis Part {chunk.chunk_index + 1} of {chunk.total_chunks}**\n"
                "You are reviewing a SUBSET of this customer's documents. "
                "If a question cannot be answered from the documents below, "
                'answer "NOT_ADDRESSED" — another chunk may contain the answer.\n'
            )

        for seg in chunk.file_segments:
            page_info = ""
            if seg.is_partial and seg.start_page is not None:
                page_info = (
                    f" (Pages {seg.start_page}-{seg.end_page}"
                    f" of {seg.total_pages},"
                    f" Part {seg.part_number} of {seg.total_parts})"
                )
            elif seg.is_partial:
                page_info = f" (Part {seg.part_number} of {seg.total_parts})"

            doc_block = f"\n---\n## Document: {seg.file_path}{page_info}\n---\n{seg.text}\n"
            parts.append(doc_block)

        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Phase 2: Merge chunk results
    # ------------------------------------------------------------------

    def _merge_chunk_results(
        self,
        chunk_results: list[SearchCustomerResult],
        customer: CustomerEntry,
        files_with_text: int,
        skipped_files: list[str],
    ) -> tuple[SearchCustomerResult, list[str]]:
        """Mechanically merge results from multiple chunks.

        Per column: answer priority YES > NO > NOT_ADDRESSED.
        Detects conflicts where chunks DISAGREE (both YES and NO).

        Returns
        -------
        tuple[SearchCustomerResult, list[str]]
            The merged result and a list of conflicted column names.
        """
        merged_columns: dict[str, SearchColumnResult] = {}
        conflicted_columns: list[str] = []
        merged_incomplete: list[str] = []

        for col in self._prompts.columns:
            answers: list[str] = []
            all_citations: list[SearchCitation] = []
            best_confidence = ""
            best_answer = "NOT_ADDRESSED"
            best_priority = 0

            for cr in chunk_results:
                col_result = cr.columns.get(col.name)
                if col_result is None:
                    continue

                answer_upper = col_result.answer.upper().strip()

                # Classify the answer.  Answers that START with
                # "NOT_ADDRESSED" (e.g. "NOT_ADDRESSED. The portions...")
                # are still NOT_ADDRESSED — don't promote them to free-text.
                if answer_upper == "YES":
                    priority = 3
                elif answer_upper == "NO":
                    priority = 2
                elif answer_upper.startswith("NOT_ADDRESSED") or answer_upper.startswith("NOT ADDRESSED"):
                    priority = 1
                else:
                    # Substantive free-text (higher than NOT_ADDRESSED).
                    priority = 2

                # For the canonical YES/NO answer we track for conflict
                # detection, normalise to the short form.
                if priority == 1:
                    answers.append("NOT_ADDRESSED")
                elif answer_upper in ("YES", "NO"):
                    answers.append(answer_upper)
                else:
                    answers.append(answer_upper)

                # When tied at the same priority, prefer the longer
                # substantive text (plan spec: "longest substantive
                # answer").  This ensures a real summary beats a terse
                # placeholder at the same priority level.
                is_better = priority > best_priority or (
                    priority == best_priority and len(col_result.answer) > len(best_answer)
                )

                if is_better:
                    best_priority = priority
                    best_answer = col_result.answer
                    best_confidence = col_result.confidence.upper()

                all_citations.extend(col_result.citations)

            # Conflict detection: both YES and NO present.
            answer_set = {a for a in answers if a in ("YES", "NO")}
            if answer_set == {"YES", "NO"}:
                conflicted_columns.append(col.name)

            # Deduplicate citations by (file_path, page, section_ref).
            seen_keys: set[tuple[str, str, str]] = set()
            deduped_citations: list[SearchCitation] = []
            for cit in all_citations:
                key = (cit.file_path, cit.page, cit.section_ref)
                if key not in seen_keys:
                    seen_keys.add(key)
                    deduped_citations.append(cit)

            merged_columns[col.name] = SearchColumnResult(
                answer=best_answer,
                confidence=best_confidence,
                citations=deduped_citations,
            )

        # Collect incomplete columns from any chunk.
        for cr in chunk_results:
            for ic in cr.incomplete_columns:
                if ic not in merged_incomplete:
                    merged_incomplete.append(ic)

        error_msg = None
        if merged_incomplete:
            error_msg = f"Incomplete response — missing columns: {', '.join(merged_incomplete)}"

        merged = SearchCustomerResult(
            customer_name=customer.name,
            group=customer.group,
            files_analyzed=files_with_text,
            total_files=customer.file_count,
            skipped_files=skipped_files,
            columns=merged_columns,
            incomplete_columns=merged_incomplete,
            error=error_msg,
        )

        return merged, conflicted_columns

    # ------------------------------------------------------------------
    # Phase 3: Synthesis (conflict resolution)
    # ------------------------------------------------------------------

    async def _synthesis_pass(
        self,
        merged: SearchCustomerResult,
        chunk_results: list[SearchCustomerResult],
        conflicted_columns: list[str],
        customer: CustomerEntry,
    ) -> SearchCustomerResult:
        """Resolve conflicts using a lightweight LLM call with all findings as JSON.

        Only called when chunks DISAGREE on YES vs NO for some columns.
        The synthesis prompt includes document type metadata to help the
        model reason about contractual precedence.
        """
        # Build compact findings JSON for the synthesis prompt.
        findings: dict[str, list[dict[str, Any]]] = {}
        for i, cr in enumerate(chunk_results):
            for col_name in conflicted_columns:
                col_result = cr.columns.get(col_name)
                if col_result is None:
                    continue
                findings.setdefault(col_name, []).append(
                    {
                        "chunk": i + 1,
                        "answer": col_result.answer,
                        "confidence": col_result.confidence,
                        "citations": [
                            {
                                "file_path": c.file_path,
                                "page": c.page,
                                "section_ref": c.section_ref,
                                "exact_quote": c.exact_quote[:200],  # Truncate for compactness
                                "doc_type": self._infer_doc_type(c.file_path),
                            }
                            for c in col_result.citations
                        ],
                    }
                )

        column_names_list = ", ".join(f'"{c}"' for c in conflicted_columns)

        synthesis_system = (
            "You are a meticulous legal due-diligence analyst resolving conflicting "
            "findings from a chunked document analysis.\n\n"
            "## Rules\n"
            "- Amendments and addenda override base agreements they modify\n"
            "- More recent documents generally take precedence over older ones\n"
            "- Look at the doc_type and citation evidence to determine which answer is correct\n"
            "- Combine partial information from multiple chunks into a unified answer\n"
            "- Preserve ALL relevant citations from chunks that support the winning answer\n\n"
            "## Output Format\n"
            "Return ONLY raw JSON with these keys: " + column_names_list + "\n"
            "Use the same structure as the original analysis:\n"
            '  {"<column>": {"answer": "...", "confidence": "...", "citations": [...]}}\n'
        )

        synthesis_user = (
            f"# Customer: {customer.name}\n\n"
            "The following columns had CONFLICTING answers across document chunks.\n"
            "Review the evidence and determine the correct answer for each.\n\n"
            f"## Conflicting Findings\n\n```json\n{json.dumps(findings, indent=2)}\n```\n"
        )

        try:
            raw_text = await self._call_claude(synthesis_system, synthesis_user)
            cleaned = self._extract_json_text(raw_text)
            data: dict[str, Any] = json.loads(cleaned) if cleaned else {}
        except Exception as exc:
            logger.warning("Synthesis pass failed for %s: %s — keeping merged results", customer.name, exc)
            return merged

        # Update only the conflicted columns with synthesis results.
        for col_name in conflicted_columns:
            col_data = data.get(col_name)
            if not isinstance(col_data, dict):
                continue

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

            merged.columns[col_name] = SearchColumnResult(
                answer=col_data.get("answer", merged.columns[col_name].answer),
                confidence=col_data.get("confidence", merged.columns[col_name].confidence),
                citations=citations or merged.columns[col_name].citations,
            )

        return merged

    # ------------------------------------------------------------------
    # Phase 4: Validation (NOT_ADDRESSED follow-up)
    # ------------------------------------------------------------------

    async def _validation_pass(
        self,
        result: SearchCustomerResult,
        file_texts: list[FileText],
        customer: CustomerEntry,
    ) -> SearchCustomerResult:
        """Re-query with targeted follow-up for remaining NOT_ADDRESSED answers.

        Uses AG-style follow-up prompting: "Pay special attention to schedules,
        exhibits, annexes, and definitions sections."  Maximum 1 pass.
        """
        not_addressed = [
            col_name for col_name, col_result in result.columns.items() if col_result.answer == "NOT_ADDRESSED"
        ]
        if not not_addressed:
            return result

        # Build focused document content: prioritise smaller files that fit together
        # (these likely contain MSA/main agreements with key provisions).
        sorted_texts = sorted(file_texts, key=lambda ft: len(ft.text))
        doc_parts: list[str] = []
        total_chars = 0
        for ft in sorted_texts:
            if total_chars + len(ft.text) > TARGET_CHUNK_CHARS:
                break
            doc_parts.append(f"\n---\n## Document: {ft.file_path}\n---\n{ft.text}\n")
            total_chars += len(ft.text)

        if not doc_parts:
            # Even the smallest file is too large; take what we can.
            ft = sorted_texts[0]
            doc_parts.append(f"\n---\n## Document: {ft.file_path}\n---\n{ft.text[:TARGET_CHUNK_CHARS]}\n")

        column_descriptions = "\n".join(
            f"- **{col.name}**: {col.prompt}" for col in self._prompts.columns if col.name in not_addressed
        )
        column_names_list = ", ".join(f'"{c}"' for c in not_addressed)

        validation_system = (
            "You are a meticulous legal due-diligence analyst performing a follow-up review.\n\n"
            "Previous analysis could NOT find answers to the questions below.\n"
            "Pay special attention to schedules, exhibits, annexes, and definitions sections.\n"
            "Previous analysis did not find answers to these questions — re-examine carefully.\n\n"
            f"## Questions to Answer\n\n{column_descriptions}\n\n"
            "## Output Format\n\n"
            "Return ONLY raw JSON with these keys: " + column_names_list + "\n"
            "Use the same structure as the original analysis:\n"
            '  {"<column>": {"answer": "...", "confidence": "...", "citations": [...]}}\n'
        )

        validation_user = f"# Customer: {customer.name}\n\n" + "\n".join(doc_parts)

        try:
            raw_text = await self._call_claude(validation_system, validation_user)
            cleaned = self._extract_json_text(raw_text)
            data: dict[str, Any] = json.loads(cleaned) if cleaned else {}
        except Exception as exc:
            logger.warning("Validation pass failed for %s: %s — keeping current results", customer.name, exc)
            return result

        # Update only the NOT_ADDRESSED columns with validation results.
        for col_name in not_addressed:
            col_data = data.get(col_name)
            if not isinstance(col_data, dict):
                continue
            answer = col_data.get("answer", "")
            if not answer or answer.upper().strip() == "NOT_ADDRESSED":
                continue  # Validation didn't help for this column.

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

            result.columns[col_name] = SearchColumnResult(
                answer=answer,
                confidence=col_data.get("confidence", ""),
                citations=citations,
            )

        return result

    # ------------------------------------------------------------------
    # Document type inference
    # ------------------------------------------------------------------

    @staticmethod
    def _infer_doc_type(file_path: str) -> str:
        """Infer document type from filename keywords.

        Returns "MSA", "Amendment", "SOW", etc. or "Contract" as default.
        """
        lower_path = file_path.lower()
        for keyword, doc_type in _DOC_TYPE_KEYWORDS.items():
            if keyword in lower_path:
                return doc_type
        return "Contract"

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
                confidence=col_data.get("confidence", "").upper(),
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
        - Multiple JSON objects concatenated (extracts the first complete one)
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

        # Find the first { in the text.
        brace_pos = cleaned.find("{")
        if brace_pos == -1:
            return cleaned

        candidate = cleaned[brace_pos:]

        # Use raw_decode to extract exactly the first complete JSON object.
        # This handles the case where the model returns two JSON objects
        # back-to-back (e.g. it started answering, then restarted).
        try:
            decoder = json.JSONDecoder()
            _, end_idx = decoder.raw_decode(candidate)
            return candidate[:end_idx]
        except json.JSONDecodeError:
            # raw_decode failed — fall back to last-brace heuristic.
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

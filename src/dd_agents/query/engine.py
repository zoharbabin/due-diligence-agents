"""Query engine for natural-language questions about DD findings (Issue #124).

Uses keyword matching for simple queries and delegates to Claude
for complex natural-language questions.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from dd_agents.query.indexer import FindingIndex

logger = logging.getLogger(__name__)


class QueryResult(BaseModel):
    """Result of a natural-language query over findings."""

    answer: str = Field(description="Natural-language answer")
    sources: list[dict[str, Any]] = Field(default_factory=list, description="Supporting finding references")
    confidence: str = Field(default="medium", description="Confidence: high, medium, low")
    query_type: str = Field(default="llm", description="How query was resolved: keyword or llm")


class QueryEngine:
    """Answer natural-language questions about DD findings.

    Parameters
    ----------
    index:
        Pre-built finding index from :class:`FindingIndexer`.
    verbose:
        If ``True``, log query resolution details.
    """

    def __init__(self, index: FindingIndex, *, verbose: bool = False) -> None:
        self.index = index
        self.verbose = verbose

    async def query(self, question: str) -> QueryResult:
        """Answer *question* using the finding index.

        Attempts keyword fast-path first (for count/list queries),
        then falls back to LLM-based answer generation.
        """
        fast = self._try_keyword_query(question)
        if fast is not None:
            return fast

        # Skip LLM for empty index — nothing to analyze
        if self.index.total_findings == 0:
            return self._fallback_search(question)

        return await self._llm_query(question)

    # ------------------------------------------------------------------
    # Keyword fast-path
    # ------------------------------------------------------------------

    _COUNT_PATTERNS: list[tuple[str, str]] = [
        (r"how many (p0|p1|p2|p3|p4) (findings?|issues?|risks?)", "severity_count"),
        (r"how many findings?", "total_count"),
        (r"total (findings?|issues?|risks?)", "total_count"),
        (r"how many (customers?|subjects?)", "subject_count"),
        (r"how many (entities|companies|contracts)", "subject_count"),
    ]

    def _try_keyword_query(self, question: str) -> QueryResult | None:
        """Attempt to answer using simple keyword matching."""
        q = question.lower().strip()

        for pattern, qtype in self._COUNT_PATTERNS:
            m = re.search(pattern, q)
            if not m:
                continue

            if qtype == "severity_count":
                sev = m.group(1).upper()
                count = len(self.index.by_severity.get(sev, []))
                return QueryResult(
                    answer=f"There are {count} {sev} findings.",
                    sources=self._top_findings_for_severity(sev, limit=3),
                    confidence="high",
                    query_type="keyword",
                )

            if qtype == "total_count":
                return QueryResult(
                    answer=f"There are {self.index.total_findings} total findings.",
                    sources=[],
                    confidence="high",
                    query_type="keyword",
                )

            if qtype == "subject_count":
                count = len(self.index.by_subject)
                return QueryResult(
                    answer=f"There are {count} entities (subjects) in the analysis.",
                    sources=[],
                    confidence="high",
                    query_type="keyword",
                )

        return None

    def _top_findings_for_severity(self, severity: str, limit: int = 3) -> list[dict[str, Any]]:
        """Return top findings for a severity level as source references."""
        indices = self.index.by_severity.get(severity, [])[:limit]
        return [
            {
                "title": self.index.findings[i].get("title", ""),
                "severity": severity,
                "subject": self.index.findings[i].get("_subject_safe_name", ""),
                "category": self.index.findings[i].get("category", ""),
            }
            for i in indices
        ]

    # ------------------------------------------------------------------
    # LLM-based query
    # ------------------------------------------------------------------

    async def _llm_query(self, question: str) -> QueryResult:
        """Answer using Claude via claude_agent_sdk."""
        context = self._build_context(question)

        try:
            from claude_agent_sdk import ClaudeAgentOptions
            from claude_agent_sdk import query as sdk_query

            prompt = (
                f"You are a due diligence analyst. Answer the following question based on the findings below.\n\n"
                f"QUESTION: {question}\n\n"
                f"FINDINGS CONTEXT:\n{context}\n\n"
                f"SUMMARY: {self.index.summary}\n\n"
                f"Answer concisely. If the findings don't contain enough information, say so."
            )

            answer_parts: list[str] = []
            async for message in sdk_query(
                prompt=prompt,
                options=ClaudeAgentOptions(max_turns=1),
            ):
                content = getattr(message, "content", None)
                if content and isinstance(content, list):
                    for block in content:
                        if hasattr(block, "text"):
                            answer_parts.append(block.text)
                elif content and isinstance(content, str):
                    answer_parts.append(content)

            answer = "".join(answer_parts) or "Unable to generate answer."
            return QueryResult(
                answer=answer,
                sources=self._extract_relevant_findings(question, limit=5),
                confidence="medium",
                query_type="llm",
            )

        except ImportError:
            logger.warning("claude_agent_sdk not available; using basic keyword search")
            return self._fallback_search(question)
        except Exception as exc:
            logger.exception("LLM query failed: %s", exc)
            return self._fallback_search(question)

    def _build_context(self, question: str, max_findings: int = 30) -> str:
        """Build a context string from the most relevant findings."""
        relevant = self._extract_relevant_findings(question, limit=max_findings)
        if not relevant:
            # Fall back to severity-ordered sample
            for sev in ["P0", "P1", "P2", "P3"]:
                for i in self.index.by_severity.get(sev, [])[:10]:
                    f = self.index.findings[i]
                    relevant.append(
                        {
                            "title": f.get("title", ""),
                            "severity": f.get("severity", ""),
                            "subject": f.get("_subject_safe_name", ""),
                            "category": f.get("category", ""),
                            "description": f.get("description", ""),
                        }
                    )
                    if len(relevant) >= max_findings:
                        break
                if len(relevant) >= max_findings:
                    break

        lines: list[str] = []
        for r in relevant:
            lines.append(
                f"- [{r.get('severity', 'P3')}] {r.get('title', '')} "
                f"(subject: {r.get('subject', 'unknown')}, category: {r.get('category', '')})"
            )
            desc = r.get("description", "")
            if desc:
                lines.append(f"  {desc[:200]}")

        return "\n".join(lines) if lines else "No relevant findings found."

    def _extract_relevant_findings(self, question: str, limit: int = 10) -> list[dict[str, Any]]:
        """Extract findings most relevant to the question using keyword overlap."""
        q_words = set(question.lower().split())
        scored: list[tuple[float, int]] = []

        for idx, f in enumerate(self.index.findings):
            text = f"{f.get('title', '')} {f.get('description', '')} {f.get('category', '')}".lower()
            f_words = set(text.split())
            overlap = len(q_words & f_words)
            if overlap > 0:
                scored.append((overlap, idx))

        scored.sort(key=lambda x: -x[0])
        results: list[dict[str, Any]] = []
        for _, idx in scored[:limit]:
            f = self.index.findings[idx]
            results.append(
                {
                    "title": f.get("title", ""),
                    "severity": f.get("severity", ""),
                    "subject": f.get("_subject_safe_name", ""),
                    "category": f.get("category", ""),
                    "description": f.get("description", ""),
                }
            )
        return results

    def _fallback_search(self, question: str) -> QueryResult:
        """Basic keyword search when LLM is unavailable."""
        relevant = self._extract_relevant_findings(question, limit=5)
        if not relevant:
            return QueryResult(
                answer="No findings match your question.",
                sources=[],
                confidence="low",
                query_type="keyword",
            )

        titles = [r.get("title", "") for r in relevant[:3]]
        answer = f"Found {len(relevant)} related findings. Top matches: {'; '.join(titles)}"
        return QueryResult(
            answer=answer,
            sources=relevant,
            confidence="low",
            query_type="keyword",
        )

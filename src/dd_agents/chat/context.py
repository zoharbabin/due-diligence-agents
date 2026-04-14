"""Context assembly for Chat Mode.

Builds the system prompt (findings digest, deal context, prior memories,
behavioral constraints) and per-turn user prompts (history + question).
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

    from dd_agents.chat.history import ConversationHistory
    from dd_agents.chat.memory import ChatMemoryStore
    from dd_agents.knowledge.base import DealKnowledgeBase
    from dd_agents.knowledge.chronicle import AnalysisChronicle
    from dd_agents.query.indexer import FindingIndex

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Budget constants (chars)
# ---------------------------------------------------------------------------

_BUDGET_ROLE: int = 1_800
_BUDGET_DEAL_CONTEXT: int = 800
_BUDGET_STATS: int = 500
_BUDGET_P0P1_DIGEST: int = 5_000
_BUDGET_P2_SAMPLE: int = 2_000
_BUDGET_SUBJECTS: int = 1_500
_BUDGET_MEMORIES: int = 2_000
_BUDGET_KB_TIMELINE: int = 500

# ---------------------------------------------------------------------------
# System prompt template parts
# ---------------------------------------------------------------------------

_ROLE_AND_CONSTRAINTS = """\
You are a due diligence analyst reviewing the results of an M&A forensic \
due diligence analysis. You have access to the complete findings and to \
document analysis tools that let you search, verify citations, and read \
source documents.

RULES:
1. Answer based on the findings data and source documents. Do not fabricate findings.
2. When citing a finding, include its severity, subject, and source document.
3. When asked to verify or drill into a claim, use the document tools \
(verify_citation, search_in_file, get_page_content).
4. If you cannot answer from available data, say so clearly.
5. Do NOT attempt to use Bash, Write, Edit, or Agent tools.
6. When you discover an important insight, cross-reference, conclusion, \
or when the user confirms/corrects a fact about the deal, use the \
save_memory tool. Save concise, actionable memories (1-3 sentences) — \
not conversation summaries.
7. Use search_chat_memory to recall prior conclusions when relevant to \
the current question.
"""


class ChatContextBuilder:
    """Assembles system prompts and per-turn user prompts for chat sessions.

    Parameters
    ----------
    finding_index:
        Pre-built finding index from :class:`FindingIndexer`.
    knowledge_base:
        Deal Knowledge Base (optional).
    chronicle:
        Analysis chronicle (optional).
    memory_store:
        Persistent chat memory store (optional).
    run_dir:
        Path to the pipeline run directory (for loading metadata).
    """

    def __init__(
        self,
        finding_index: FindingIndex,
        knowledge_base: DealKnowledgeBase | None = None,
        chronicle: AnalysisChronicle | None = None,
        memory_store: ChatMemoryStore | None = None,
        run_dir: Path | None = None,
    ) -> None:
        self._index = finding_index
        self._kb = knowledge_base
        self._chronicle = chronicle
        self._memory_store = memory_store
        self._run_dir = run_dir

    def build_system_prompt(self) -> str:
        """Assemble the full system prompt (~14K chars)."""
        parts: list[str] = []

        # 1. Role and constraints
        parts.append(_ROLE_AND_CONSTRAINTS.strip())

        # 2. Deal context
        deal_ctx = self._load_deal_context()
        if deal_ctx:
            parts.append(f"\nDEAL CONTEXT:\n{deal_ctx}")

        # 3. Findings stats
        parts.append(f"\nFINDINGS OVERVIEW:\n{self._index.summary}")
        parts.append(f"Subjects: {len(self._index.by_subject)} entities analyzed.")

        # 4. P0+P1 digest
        digest = self.build_findings_digest(max_chars=_BUDGET_P0P1_DIGEST + _BUDGET_P2_SAMPLE)
        if digest:
            parts.append(f"\n{digest}")

        # 5. Subject index
        subject_section = self._build_subject_index()
        if subject_section:
            parts.append(f"\n{subject_section}")

        # 6. Prior memories from past sessions
        memories_section = self._build_memories_section()
        if memories_section:
            parts.append(f"\n{memories_section}")

        # 7. KB timeline
        timeline = self._build_timeline()
        if timeline:
            parts.append(f"\n{timeline}")

        return "\n".join(parts)

    def build_turn_prompt(
        self,
        question: str,
        history: ConversationHistory,
    ) -> str:
        """Build the user prompt for a single turn.

        Includes serialized conversation history followed by the current
        question.
        """
        parts: list[str] = []

        history_text = history.to_prompt_text()
        if history_text:
            parts.append(history_text)

        parts.append(f"\n[Current Question]\nUSER: {question}")
        return "\n".join(parts)

    def build_findings_digest(self, max_chars: int = 7_000) -> str:
        """Build a compact digest of findings ordered by severity.

        P0 and P1 findings are listed first, followed by a sample of P2.
        Each finding is formatted as a one-liner.
        """
        parts: list[str] = []
        chars_used = 0

        severity_labels = {
            "P0": "CRITICAL FINDINGS (P0):",
            "P1": "HIGH FINDINGS (P1):",
            "P2": "MEDIUM FINDINGS (P2 — sample):",
        }

        for sev in ("P0", "P1", "P2"):
            indices = self._index.by_severity.get(sev, [])
            if not indices:
                continue

            label = severity_labels.get(sev, f"{sev} FINDINGS:")
            section_lines: list[str] = [label]

            max_items = 50 if sev in ("P0", "P1") else 20
            for idx in indices[:max_items]:
                f = self._index.findings[idx]
                line = self._format_finding_oneliner(f)
                if chars_used + len(line) + len(label) > max_chars:
                    break
                section_lines.append(f"- {line}")
                chars_used += len(line) + 3  # "- " + newline

            if len(section_lines) > 1:
                parts.append("\n".join(section_lines))

        return "\n\n".join(parts)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _format_finding_oneliner(f: dict[str, Any]) -> str:
        """Format a finding as a compact one-liner."""
        domain = f.get("agent", f.get("domain", "?"))
        subject = f.get("_subject_safe_name", f.get("subject", f.get("analysis_unit", "?")))
        title = f.get("title", "Untitled")
        # Extract first citation source if available
        citations = f.get("citations", [])
        source = ""
        if citations and isinstance(citations, list) and len(citations) > 0:
            c = citations[0]
            if isinstance(c, dict):
                sp = c.get("source_path", "")
                page = c.get("page_number")
                if sp:
                    source = f" ({sp}"
                    if page:
                        source += f" p{page}"
                    source += ")"
        return f"[{domain}] {subject}: {title}{source}"

    def _load_deal_context(self) -> str:
        """Load deal context from run metadata."""
        if self._run_dir is None:
            return ""
        metadata_path = self._run_dir / "metadata.json"
        if not metadata_path.exists():
            return ""
        try:
            data = json.loads(metadata_path.read_text(encoding="utf-8"))
            parts: list[str] = []
            # Extract key fields
            for key in ("buyer", "target", "deal_type", "skill"):
                val = data.get(key)
                if val:
                    parts.append(f"{key.replace('_', ' ').title()}: {val}")
            run_id = data.get("run_id", "")
            if run_id:
                parts.append(f"Run: {run_id}")
            return "\n".join(parts) if parts else ""
        except (json.JSONDecodeError, OSError):
            return ""

    def _build_subject_index(self) -> str:
        """Build a compact subject index."""
        subjects = sorted(self._index.by_subject.keys())
        if not subjects:
            return ""
        lines = ["SUBJECTS:"]
        for s in subjects[:50]:
            count = len(self._index.by_subject[s])
            lines.append(f"  {s} ({count} findings)")
        if len(subjects) > 50:
            lines.append(f"  ... and {len(subjects) - 50} more")
        result = "\n".join(lines)
        return result[:_BUDGET_SUBJECTS]

    def _build_memories_section(self) -> str:
        """Load recent memories from past sessions for context injection."""
        if self._memory_store is None:
            return ""
        memories = self._memory_store.load_recent_memories(limit=15)
        if not memories:
            return ""

        lines = ["MEMORIES FROM PRIOR SESSIONS:"]
        chars = len(lines[0])
        for mem in memories:
            date_str = mem.timestamp[:10] if len(mem.timestamp) >= 10 else mem.timestamp
            topics_str = ", ".join(mem.topics[:5]) if mem.topics else "general"
            line = f"- [{date_str}] {mem.content} (topics: {topics_str})"
            if chars + len(line) > _BUDGET_MEMORIES:
                break
            lines.append(line)
            chars += len(line) + 1  # newline

        return "\n".join(lines) if len(lines) > 1 else ""

    def _build_timeline(self) -> str:
        """Build a brief KB timeline from the analysis chronicle."""
        if self._chronicle is None:
            return ""
        try:
            entries = self._chronicle.read_recent(limit=5)
        except Exception:
            return ""
        if not entries:
            return ""

        lines = ["RECENT ANALYSIS ACTIVITY:"]
        for entry in entries:
            ts = entry.timestamp[:10] if len(entry.timestamp) >= 10 else entry.timestamp
            lines.append(f"- [{ts}] {entry.interaction_type}: {entry.title}")
        result = "\n".join(lines)
        return result[:_BUDGET_KB_TIMELINE]

"""Pydantic models for LLM-generated report narrative.

The narrative generation step produces structured JSON consumed by HTML
renderers. It provides the interpretive layer: why findings matter for
THIS specific deal, what to do about them, and what questions remain open.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class DealContextNarrative(BaseModel):
    """2-3 sentence framing of the deal for report readers."""

    summary: str = Field(
        default="",
        description="2-3 sentences framing the deal: who is buying whom, why, and what the DD scope covers.",
    )
    buyer_thesis_alignment: str = Field(
        default="",
        description="How findings relate to the buyer's stated thesis (empty if no buyer_strategy in config).",
    )


class DomainNarrative(BaseModel):
    """Per-domain interpretive summary."""

    domain: str = Field(description="Domain identifier (e.g. 'legal', 'finance')")
    headline: str = Field(
        default="",
        description="One-sentence headline: the single most important thing about this domain.",
    )
    narrative: str = Field(
        default="",
        description="1-2 paragraph summary explaining the pattern of findings, combined significance, and what to do.",
    )
    open_questions: list[str] = Field(
        default_factory=list,
        description="What data is missing or needs specialist review for this domain.",
    )


class FindingNarrative(BaseModel):
    """Per-finding 'so what' commentary for P0/P1 findings."""

    finding_title: str = Field(description="Title of the finding this narrative applies to")
    entity: str = Field(default="", description="Entity/subject the finding relates to")
    severity: str = Field(default="", description="Finding severity (P0, P1)")
    so_what: str = Field(
        default="",
        description="Plain-language explanation of why this matters for THIS deal.",
    )
    criteria: str = Field(
        default="",
        description="What 'good' looks like — the standard or expectation being violated.",
    )
    impact: str = Field(
        default="",
        description="Concrete impact: dollars, timeline, or strategic consequence for the buyer.",
    )
    recommended_action: str = Field(
        default="",
        description="Specific recommended next step (not generic advice).",
    )


class NarrativeRecommendation(BaseModel):
    """Context-aware recommendation tied to specific findings."""

    action: str = Field(description="Specific, actionable recommendation.")
    rationale: str = Field(
        default="",
        description="Why this action matters — business justification tied to deal context.",
    )
    finding_refs: list[str] = Field(
        default_factory=list,
        description="Titles of findings that motivate this recommendation.",
    )
    owner: str = Field(
        default="",
        description="Suggested owner: Legal Counsel, M&A Counsel, Deal Team, CFO, CTO, etc.",
    )
    urgency: str = Field(
        default="pre-close",
        description="Timeline: pre-close, day-1, 30-day, 90-day, long-term.",
    )
    estimated_effort: str = Field(
        default="",
        description="Rough effort: hours, days, or weeks.",
    )


class OpenQuestion(BaseModel):
    """Something that needs resolution — missing data, specialist input, or decision."""

    question: str = Field(description="The specific question or gap.")
    category: str = Field(
        default="data_gap",
        description="Category: data_gap, needs_counsel, needs_auditor, cost_estimate, decision_required.",
    )
    related_domains: list[str] = Field(
        default_factory=list,
        description="Domains this question relates to.",
    )
    priority: str = Field(
        default="medium",
        description="Priority: high (blocks decision), medium (informs decision), low (nice to have).",
    )


class NarrativeOutput(BaseModel):
    """Complete narrative generation output.

    Structured JSON consumed by HTML renderers. Deterministic structure,
    LLM-generated content. All fields have safe defaults so reports render
    correctly even with partial output.
    """

    deal_context: DealContextNarrative = Field(
        default_factory=DealContextNarrative,
        description="Deal framing for report readers.",
    )
    domain_summaries: list[DomainNarrative] = Field(
        default_factory=list,
        description="Per-domain interpretive summaries.",
    )
    finding_narratives: list[FindingNarrative] = Field(
        default_factory=list,
        description="Per-finding 'so what' commentary for P0/P1 findings.",
    )
    recommendations: list[NarrativeRecommendation] = Field(
        default_factory=list,
        description="Prioritized, context-aware action items.",
    )
    open_questions: list[OpenQuestion] = Field(
        default_factory=list,
        description="Gaps, questions, and items needing specialist input.",
    )
    config_guidance: str = Field(
        default="",
        description="Guidance for improving deal config (shown when config is minimal).",
    )

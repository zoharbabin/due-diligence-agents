"""dd_agents.agents subpackage -- agent runner classes and prompt builder."""

from __future__ import annotations

from dd_agents.agents.acquirer_intelligence import (
    ACQUIRER_INTELLIGENCE_TOOLS,
    AcquirerIntelligenceAgent,
    AcquirerIntelligenceOutput,
)
from dd_agents.agents.base import BaseAgentRunner
from dd_agents.agents.descriptor import AgentDescriptor
from dd_agents.agents.executive_synthesis import (
    EXECUTIVE_SYNTHESIS_TOOLS,
    ExecutiveSynthesisAgent,
    ExecutiveSynthesisOutput,
)
from dd_agents.agents.judge import (
    DEFAULT_SAMPLING_RATES,
    DEFAULT_SCORE_THRESHOLD,
    DIMENSION_WEIGHTS,
    JudgeAgent,
    blend_round_scores,
    calculate_agent_score,
)
from dd_agents.agents.prompt_builder import (
    SPECIALIST_FOCUS,
    AgentType,
    PromptBuilder,
)
from dd_agents.agents.red_flag_scanner import (
    RED_FLAG_CATEGORIES,
    RED_FLAG_TOOLS,
    RedFlagScannerAgent,
    RedFlagScannerOutput,
    classify_signal,
)
from dd_agents.agents.registry import AgentRegistry
from dd_agents.agents.specialists import (
    COMMERCIAL_FOCUS_AREAS,
    CYBERSECURITY_FOCUS_AREAS,
    ESG_FOCUS_AREAS,
    FINANCE_FOCUS_AREAS,
    HR_FOCUS_AREAS,
    LEGAL_FOCUS_AREAS,
    PRODUCTTECH_FOCUS_AREAS,
    REGULATORY_FOCUS_AREAS,
    SPECIALIST_CLASSES,
    SPECIALIST_TYPES,
    TAX_FOCUS_AREAS,
    CommercialAgent,
    CybersecurityAgent,
    ESGAgent,
    FinanceAgent,
    HRAgent,
    LegalAgent,
    ProductTechAgent,
    RegulatoryAgent,
    TaxAgent,
)

__all__ = [
    # Base
    "BaseAgentRunner",
    # Registry
    "AgentDescriptor",
    "AgentRegistry",
    # Prompt builder
    "AgentType",
    "PromptBuilder",
    "SPECIALIST_FOCUS",
    # Acquirer Intelligence
    "AcquirerIntelligenceAgent",
    "AcquirerIntelligenceOutput",
    "ACQUIRER_INTELLIGENCE_TOOLS",
    # Specialists
    "LegalAgent",
    "FinanceAgent",
    "CommercialAgent",
    "ProductTechAgent",
    "CybersecurityAgent",
    "HRAgent",
    "TaxAgent",
    "RegulatoryAgent",
    "ESGAgent",
    "LEGAL_FOCUS_AREAS",
    "FINANCE_FOCUS_AREAS",
    "COMMERCIAL_FOCUS_AREAS",
    "PRODUCTTECH_FOCUS_AREAS",
    "CYBERSECURITY_FOCUS_AREAS",
    "HR_FOCUS_AREAS",
    "TAX_FOCUS_AREAS",
    "REGULATORY_FOCUS_AREAS",
    "ESG_FOCUS_AREAS",
    "SPECIALIST_TYPES",
    "SPECIALIST_CLASSES",
    # Executive Synthesis
    "ExecutiveSynthesisAgent",
    "ExecutiveSynthesisOutput",
    "EXECUTIVE_SYNTHESIS_TOOLS",
    # Red Flag Scanner
    "RedFlagScannerAgent",
    "RedFlagScannerOutput",
    "RED_FLAG_CATEGORIES",
    "RED_FLAG_TOOLS",
    "classify_signal",
    # Judge
    "JudgeAgent",
    "DEFAULT_SAMPLING_RATES",
    "DEFAULT_SCORE_THRESHOLD",
    "DIMENSION_WEIGHTS",
    "calculate_agent_score",
    "blend_round_scores",
]

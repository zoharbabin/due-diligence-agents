"""dd_agents.agents subpackage -- agent runner classes and prompt builder."""

from __future__ import annotations

from dd_agents.agents.acquirer_intelligence import (
    ACQUIRER_INTELLIGENCE_TOOLS,
    AcquirerIntelligenceAgent,
)
from dd_agents.agents.base import BaseAgentRunner
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
from dd_agents.agents.specialists import (
    COMMERCIAL_FOCUS_AREAS,
    FINANCE_FOCUS_AREAS,
    LEGAL_FOCUS_AREAS,
    PRODUCTTECH_FOCUS_AREAS,
    SPECIALIST_CLASSES,
    SPECIALIST_TYPES,
    CommercialAgent,
    FinanceAgent,
    LegalAgent,
    ProductTechAgent,
)

__all__ = [
    # Base
    "BaseAgentRunner",
    # Prompt builder
    "AgentType",
    "PromptBuilder",
    "SPECIALIST_FOCUS",
    # Acquirer Intelligence
    "AcquirerIntelligenceAgent",
    "ACQUIRER_INTELLIGENCE_TOOLS",
    # Specialists
    "LegalAgent",
    "FinanceAgent",
    "CommercialAgent",
    "ProductTechAgent",
    "LEGAL_FOCUS_AREAS",
    "FINANCE_FOCUS_AREAS",
    "COMMERCIAL_FOCUS_AREAS",
    "PRODUCTTECH_FOCUS_AREAS",
    "SPECIALIST_TYPES",
    "SPECIALIST_CLASSES",
    # Judge
    "JudgeAgent",
    "DEFAULT_SAMPLING_RATES",
    "DEFAULT_SCORE_THRESHOLD",
    "DIMENSION_WEIGHTS",
    "calculate_agent_score",
    "blend_round_scores",
]

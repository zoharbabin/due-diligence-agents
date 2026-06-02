"""Analyst Configuration panel renderer (audit §6.6).

Surfaces, in the report itself, exactly which specialist agents ran, which
were disabled, and any per-agent persona / severity / focus overrides in
effect — so a reader can see how the analysis was configured without opening
the deal config.  Reads the raw deal-config dict from the renderer config
(``_deal_config``) via dict-walk (the config is an untyped dict in report
state) at ``forensic_dd.specialists.{disabled,customizations}``.

Uses only CSS classes already defined in :mod:`html_base` (``report-section``,
``subject-table``, ``alert``/``alert-*`` via :meth:`render_alert`,
``text-muted``).  All user-supplied strings are escaped (XSS-safe).
"""

from __future__ import annotations

from typing import Any

from dd_agents.agents.registry import AgentRegistry
from dd_agents.reporting.html_base import SectionRenderer


class ConfigPanelRenderer(SectionRenderer):
    """Render the 'Analyst Configuration' panel for the report."""

    def render(self) -> str:
        deal_config = self.config.get("_deal_config")
        if not isinstance(deal_config, dict):
            deal_config = {}

        specialists = (
            deal_config.get("forensic_dd", {}) if isinstance(deal_config.get("forensic_dd"), dict) else {}
        ).get("specialists", {})
        if not isinstance(specialists, dict):
            specialists = {}

        disabled_raw = specialists.get("disabled", [])
        disabled = [str(d) for d in disabled_raw] if isinstance(disabled_raw, list) else []

        customizations_raw = specialists.get("customizations", {})
        customizations = customizations_raw if isinstance(customizations_raw, dict) else {}

        # Agents that actually ran = registered specialists minus disabled.
        all_specialists = AgentRegistry.all_specialist_names()
        disabled_set = {d.lower() for d in disabled}
        enabled = [a for a in all_specialists if a.lower() not in disabled_set]

        override_rows = self._build_override_rows(customizations)

        parts: list[str] = [
            "<section class='report-section' id='sec-analyst-config'>",
            "<h2>Analyst Configuration</h2>",
        ]

        # Nothing customized at all — render a single default note and return.
        if not disabled and not override_rows:
            parts.append(
                self.render_alert(
                    "info",
                    "Default configuration",
                    "Default configuration — all agents enabled, no overrides.",
                )
            )
            parts.append("</section>")
            return "\n".join(parts)

        # Agents that ran.
        if enabled:
            parts.append("<p class='text-muted'>Agents that ran: " + self.escape(", ".join(enabled)) + "</p>")

        # Disabled agents.
        if disabled:
            parts.append(
                self.render_alert(
                    "info",
                    "Disabled agents",
                    "The following agents were disabled for this run: " + ", ".join(disabled),
                )
            )

        # Per-agent overrides table.
        if override_rows:
            parts.append("<table class='subject-table sortable'><thead><tr>")
            parts.append(
                "<th scope='col'>Agent</th><th scope='col'>Override</th><th scope='col'>Detail</th></tr></thead><tbody>"
            )
            for agent, kind, detail in override_rows:
                parts.append(
                    f"<tr><td>{self.escape(agent)}</td><td>{self.escape(kind)}</td><td>{self.escape(detail)}</td></tr>"
                )
            parts.append("</tbody></table>")

        parts.append("</section>")
        return "\n".join(parts)

    def _build_override_rows(self, customizations: dict[str, Any]) -> list[tuple[str, str, str]]:
        """Flatten per-agent customizations into (agent, kind, detail) rows.

        Tolerant of both AgentCustomization-like mappings and raw dicts; only
        non-empty overrides produce rows.  Detail strings are rendered escaped
        by the caller.
        """
        rows: list[tuple[str, str, str]] = []
        for agent_name, cust in sorted(customizations.items()):
            if not isinstance(cust, dict):
                continue
            agent = str(agent_name)

            persona = cust.get("persona")
            if isinstance(persona, str) and persona.strip():
                rows.append((agent, "Persona override", persona))

            sev = cust.get("severity_overrides")
            if isinstance(sev, dict) and sev:
                # sorted() for deterministic output — dict insertion order varies
                # by source file/loader and would cause HTML diff noise (Copilot #202 C9).
                detail = ", ".join(f"{k}→{v}" for k, v in sorted(sev.items()))
                rows.append((agent, "Severity override", detail))

            focus = cust.get("extra_focus_areas")
            if isinstance(focus, list) and focus:
                rows.append((agent, "Extra focus areas", ", ".join(str(f) for f in focus)))

            instr = cust.get("extra_instructions")
            if isinstance(instr, str) and instr.strip():
                rows.append((agent, "Extra instructions", instr))

        return rows

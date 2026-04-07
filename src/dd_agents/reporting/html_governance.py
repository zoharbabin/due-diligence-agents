"""Governance Graph Visualization renderer (Issue #142).

Renders an interactive Mermaid.js directed graph showing document
governance relationships per entity, with cycle detection alerts.
"""

from __future__ import annotations

import re
from typing import Any

from dd_agents.reporting.html_base import SectionRenderer

# Mermaid edge styles by relationship type
_RELATIONSHIP_STYLES: dict[str, str] = {
    "governs": "-->",
    "amends": "-.->",
    "supersedes": "==>",
    "references": "-..->",
}


def _sanitize_mermaid_id(text: str) -> str:
    """Create a safe Mermaid node ID from a file path."""
    return re.sub(r"[^a-zA-Z0-9_]", "_", text)[:40]


def _sanitize_mermaid_label(text: str) -> str:
    """Sanitize text for use inside Mermaid node labels (``["..."]``).

    Strips characters that break Mermaid syntax: quotes, brackets, pipes,
    backticks, angle brackets, and braces.
    """
    return re.sub(r'["\[\]|`<>{}]', "", text)[:60]


def _short_name(file_path: str) -> str:
    """Extract a short display name from a file path."""
    parts = file_path.replace("\\", "/").split("/")
    return parts[-1] if parts else file_path


class GovernanceGraphRenderer(SectionRenderer):
    """Render governance graph visualization using Mermaid diagrams."""

    def render(self) -> str:
        graphs = self._collect_graphs()
        if not graphs:
            return ""

        parts: list[str] = [
            "<section class='report-section' id='sec-gov-graph'>",
            "<h2>Governance Graph</h2>",
            "<p class='text-muted'>Document governance relationships showing how contracts "
            "reference, amend, or supersede each other.</p>",
        ]

        # Aggregate stats
        total_edges = sum(len(edges) for edges in graphs.values())
        total_entities = len(graphs)
        parts.append(
            "<div class='metrics-strip'>"
            f"<div class='metric-card'><div class='value'>{total_entities}</div>"
            "<div class='label'>Entities with Graphs</div></div>"
            f"<div class='metric-card'><div class='value'>{total_edges}</div>"
            "<div class='label'>Document Relationships</div></div>"
            "</div>"
        )

        # Check for cycles across all entities
        all_cycles: list[tuple[str, list[str]]] = []
        for entity_name, edges in graphs.items():
            cycles = self._detect_cycles(edges)
            for cycle in cycles:
                all_cycles.append((entity_name, cycle))

        if all_cycles:
            cycle_desc = "; ".join(f"{entity}: {' -> '.join(c)}" for entity, c in all_cycles[:5])
            parts.append(
                self.render_alert(
                    "critical",
                    f"Governance Cycle Detected ({len(all_cycles)} cycle(s))",
                    f"Circular governance references found: {cycle_desc}. "
                    "This may indicate conflicting contract hierarchies.",
                )
            )

        # Render legend
        parts.append(self._render_legend())

        # Render per-entity graphs (capped at 10 for readability)
        for entity_name, edges in list(graphs.items())[:10]:
            parts.append(self._render_entity_graph(entity_name, edges))

        # Mermaid JS (client-side rendering)
        parts.append(
            "<script src='https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js'></script>"
            "<script>mermaid.initialize({startOnLoad:true, theme:'neutral', "
            "securityLevel:'strict'});</script>"
        )

        parts.append("</section>")
        return "\n".join(parts)

    def _collect_graphs(self) -> dict[str, list[dict[str, Any]]]:
        """Collect governance graph edges from merged data."""
        result: dict[str, list[dict[str, Any]]] = {}
        for csn, cust_data in self.merged_data.items():
            if not isinstance(cust_data, dict):
                continue
            gov = cust_data.get("governance_graph")
            if not gov or not isinstance(gov, dict):
                continue
            edges = gov.get("edges", [])
            if edges:
                display = cust_data.get("customer", csn)
                result[display] = edges
        return result

    def _render_entity_graph(self, entity_name: str, edges: list[dict[str, Any]]) -> str:
        """Render a Mermaid diagram for one entity."""
        parts: list[str] = [
            f"<h3>{self.escape(entity_name)}</h3>",
            "<div class='mermaid'>",
            "graph LR",
        ]

        # Collect unique nodes and edges
        nodes: set[str] = set()
        for edge in edges:
            from_file = str(edge.get("from_file", ""))
            to_file = str(edge.get("to_file", ""))
            if not from_file or not to_file:
                continue

            from_id = _sanitize_mermaid_id(from_file)
            to_id = _sanitize_mermaid_id(to_file)
            from_label = _sanitize_mermaid_label(_short_name(from_file))
            to_label = _sanitize_mermaid_label(_short_name(to_file))
            rel = str(edge.get("relationship", "references")).lower()
            arrow = _RELATIONSHIP_STYLES.get(rel, "-->")

            # Define nodes with labels
            if from_id not in nodes:
                parts.append(f'    {from_id}["{from_label}"]')
                nodes.add(from_id)
            if to_id not in nodes:
                parts.append(f'    {to_id}["{to_label}"]')
                nodes.add(to_id)

            parts.append(f"    {from_id} {arrow}|{_sanitize_mermaid_label(rel)}| {to_id}")

        parts.append("</div>")
        return "\n".join(parts)

    def _render_legend(self) -> str:
        """Render a legend for relationship types."""
        items: list[str] = [
            "<div style='display:flex;gap:16px;flex-wrap:wrap;margin:12px 0;font-size:0.85em'>",
        ]
        legends = [
            ("governs", "solid arrow", "#4a90d9"),
            ("amends", "dashed arrow", "#fd7e14"),
            ("supersedes", "thick arrow", "#dc3545"),
            ("references", "dotted arrow", "#6c757d"),
        ]
        for rel, desc, color in legends:
            items.append(
                f"<span style='display:flex;align-items:center;gap:4px'>"
                f"<span style='width:24px;height:3px;background:{color};display:inline-block'></span>"
                f"<strong>{self.escape(rel)}</strong> ({desc})</span>"
            )
        items.append("</div>")
        return "".join(items)

    @staticmethod
    def _detect_cycles(edges: list[dict[str, Any]]) -> list[list[str]]:
        """Detect cycles in a set of edges using networkx."""
        import networkx as nx

        graph: nx.DiGraph[str] = nx.DiGraph()
        for edge in edges:
            from_file = str(edge.get("from_file", ""))
            to_file = str(edge.get("to_file", ""))
            if from_file and to_file:
                graph.add_edge(from_file, to_file)
        return [list(c) for c in nx.simple_cycles(graph)]

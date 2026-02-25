from __future__ import annotations

from pydantic import BaseModel, Field


class GovernanceCitation(BaseModel):
    """Citation proving a governance relationship."""

    source_path: str = ""
    location: str = ""
    exact_quote: str = ""


class GovernanceEdge(BaseModel):
    """
    A directed edge in the governance graph.
    From domain-definitions.md section 5b.
    """

    from_file: str = Field(description="Source file path (the governed document)")
    to_file: str = Field(description="Target file path (the governing document)")
    link_reason: str = ""  # "explicit reference", etc.
    relationship: str = ""  # governs, amends, supersedes, references
    citation: GovernanceCitation = Field(default_factory=GovernanceCitation)


class GovernanceGraph(BaseModel):
    """
    Structured governance graph for a customer.
    From domain-definitions.md section 5b.

    IMPORTANT: This is a structured Pydantic model with an edges list,
    NOT a plain dict. This ensures type safety and validation throughout
    the pipeline.
    """

    edges: list[GovernanceEdge] = Field(default_factory=list)

    def get_governing_doc(self, file_path: str) -> str | None:
        """Return the governing document for a given file, or None."""
        for edge in self.edges:
            if edge.from_file == file_path:
                return edge.to_file
        return None

    def get_governed_docs(self, file_path: str) -> list[str]:
        """Return all documents governed by the given file."""
        return [edge.from_file for edge in self.edges if edge.to_file == file_path]

    def get_unresolved_files(self, all_files: list[str]) -> list[str]:
        """Return files that have no governance edge (not in any from_file)."""
        governed = {edge.from_file for edge in self.edges}
        # Files that are targets (governing docs) or self-governing don't need edges
        targets = {edge.to_file for edge in self.edges}
        return [f for f in all_files if f not in governed and f not in targets]

    def has_cycles(self) -> list[list[str]]:
        """Detect governance cycles using ``networkx.simple_cycles()``.

        Returns a list of cycle paths (each cycle is a list of file paths).
        Handles disconnected components correctly.
        """
        import networkx as nx

        graph: nx.DiGraph[str] = nx.DiGraph()
        for edge in self.edges:
            graph.add_edge(edge.from_file, edge.to_file)
        return [list(c) for c in nx.simple_cycles(graph)]

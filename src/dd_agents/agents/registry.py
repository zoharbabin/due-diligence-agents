"""AgentRegistry — single source of truth for specialist agents.

All pipeline subsystems query the registry instead of importing
``ALL_SPECIALIST_AGENTS`` or ``SPECIALIST_CLASSES`` directly.
Built-in agents self-register at import time (see ``specialists.py``).
External agents register via ``dd_agents.specialists`` entry-points.
"""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from dd_agents.agents.descriptor import AgentDescriptor
    from dd_agents.models.config import DealConfig

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_descriptors: dict[str, AgentDescriptor] = {}
_builtins_loaded = False


def _ensure_builtins() -> None:
    """Lazy-import ``specialists`` to trigger self-registration.

    Thread-safety: the check-then-set of ``_builtins_loaded`` is performed
    inside ``_lock`` so that exactly one thread wins the race.  The flag is
    set **before** releasing the lock, so every other thread that enters the
    critical section afterwards sees ``True`` and returns immediately.  The
    actual import + registration happens *outside* the lock (only by the
    winning thread) to avoid a potential deadlock — ``_register_builtins``
    calls ``AgentRegistry.register``, which acquires ``_lock`` itself.
    """
    global _builtins_loaded  # noqa: PLW0603
    with _lock:
        if _builtins_loaded:
            return
        _builtins_loaded = True
    # Import and register outside the lock — register() re-acquires _lock
    # safely and no other thread will reach this point (flag already True).
    from dd_agents.agents.specialists import _register_builtins

    _register_builtins()


class AgentRegistry:
    """Thread-safe singleton registry for specialist agent descriptors."""

    @staticmethod
    def register(descriptor: AgentDescriptor) -> None:
        """Register (or re-register) a specialist agent descriptor."""
        with _lock:
            if descriptor.name in _descriptors:
                logger.debug("Re-registering agent '%s'", descriptor.name)
            _descriptors[descriptor.name] = descriptor

    @staticmethod
    def get(name: str) -> AgentDescriptor:
        """Return the descriptor for *name*, or raise ``KeyError``."""
        _ensure_builtins()
        with _lock:
            if name not in _descriptors:
                known = ", ".join(sorted(_descriptors)) or "(none)"
                raise KeyError(f"No agent registered with name '{name}'. Registered agents: {known}")
            return _descriptors[name]

    @staticmethod
    def all_specialist_names() -> list[str]:
        """Return names of all registered specialist agents (insertion order)."""
        _ensure_builtins()
        with _lock:
            return list(_descriptors)

    @staticmethod
    def resolve_active(deal_config: DealConfig | None = None) -> list[str]:
        """Return agent names to actually run, respecting config disablement.

        1. Start with all registered specialists (insertion order).
        2. Remove any names listed in ``deal_config.forensic_dd.specialists.disabled``.
        3. Warn on unknown names in the disabled list.
        """
        _ensure_builtins()
        with _lock:
            all_names = list(_descriptors)

        if deal_config is None:
            return all_names

        forensic_dd = getattr(deal_config, "forensic_dd", None)
        specialists_cfg = getattr(forensic_dd, "specialists", None)
        disabled: list[str] = getattr(specialists_cfg, "disabled", []) or []

        if not disabled:
            return all_names

        disabled_set = set(disabled)
        unknown = disabled_set - set(all_names)
        if unknown:
            logger.warning(
                "specialists.disabled references unknown agents: %s (known: %s)",
                sorted(unknown),
                sorted(all_names),
            )

        return [n for n in all_names if n not in disabled_set]

    @staticmethod
    def collect_persona_texts(
        active: list[str] | None = None,
        project_dir: object | None = None,
    ) -> dict[str, str]:
        """Return ``{agent_name: persona_text}`` for provenance hashing (§8.1).

        Instantiates each active runner with placeholder paths (``get_system_prompt``
        returns static persona text and does not touch disk) and records a
        per-agent safety-floor entry so floor/citation-mandate edits bust the hash.

        When *project_dir* is provided, also folds each agent's RESOLVED
        ``dd-config/`` customization (persona / focus / instructions / severity +
        ``extends`` profile chain) into the hashed text. Without this, editing a
        ``dd-config/agents/*.md`` file would change assembled prompts but NOT the
        provenance hash, letting a checkpoint resume against drifted prompts
        (Copilot #202 C5). Pure with respect to anything outside *project_dir*.
        """
        from pathlib import Path

        from dd_agents.agents.prompt_constants import assemble_safety_floor

        names = active if active is not None else AgentRegistry.all_specialist_names()
        placeholder = Path("/nonexistent")
        texts: dict[str, str] = {}
        for name in names:
            try:
                descriptor = AgentRegistry.get(name)
                runner = descriptor.agent_class(project_dir=placeholder, run_dir=placeholder, run_id="provenance")
                texts[name] = runner.get_system_prompt()
                # Record the PER-AGENT safety floor too. assemble_safety_floor()
                # embeds build_citation_mandate(agent_type), whose examples differ
                # per agent — so a change to (e.g.) Finance citation examples must
                # bust this agent's provenance, not just legal's (Copilot #202 C3).
                texts[f"_SAFETY_FLOOR::{name}"] = assemble_safety_floor(name)
                # Fold the resolved dd-config customization (markdown overrides +
                # extends profiles) so editing them busts the hash (Copilot #202 C5).
                if project_dir is not None:
                    cust_text = AgentRegistry._resolved_customization_text(Path(str(project_dir)), name)
                    if cust_text:
                        texts[f"_DD_CONFIG::{name}"] = cust_text
            except Exception:  # noqa: BLE001 — provenance must never crash a run
                logger.warning("Could not collect persona text for agent '%s'", name, exc_info=True)
        return texts

    @staticmethod
    def _resolved_customization_text(project_dir: object, agent: str) -> str:
        """Stable text of an agent's resolved dd-config customization, or "".

        Folds the ``extends`` profile chain + ``dd-config/agents/{agent}.md`` into
        a canonical string for provenance hashing. Deal-config inline overrides
        are already covered by the config hash, so only the dd-config layers are
        included here (project_dir-only). Returns "" if there is no dd-config.
        """
        from pathlib import Path

        from dd_agents.customization.loader import resolve_chain

        dd_config_dir = Path(str(project_dir)) / "dd-config"
        if not dd_config_dir.is_dir():
            return ""
        try:
            profiles_dir = Path(__file__).resolve().parent.parent / "customization" / "profiles"
            resolved = resolve_chain(agent, dd_config_dir, None, profiles_dir)
        except Exception:  # noqa: BLE001 — malformed config must not crash provenance
            return ""
        c = resolved.customization
        # Canonical, order-stable serialization of the customization fields.
        parts = [
            f"persona={c.persona or ''}",
            f"focus={'|'.join(c.extra_focus_areas)}",
            f"instructions={c.extra_instructions or ''}",
            f"severity={'|'.join(f'{k}:{v}' for k, v in sorted(c.severity_overrides.items()))}",
            f"layers={'|'.join(resolved.layer_hashes)}",
        ]
        return "\n".join(parts)

    @staticmethod
    def discover_entry_points() -> None:
        """Load agents from the ``dd_agents.specialists`` entry-points group."""
        try:
            from importlib.metadata import entry_points
        except ImportError:
            return

        eps = entry_points(group="dd_agents.specialists")
        for ep in eps:
            try:
                factory = ep.load()
                descriptor: AgentDescriptor = factory()
                AgentRegistry.register(descriptor)
                logger.info(
                    "Loaded external agent '%s' from %s",
                    descriptor.name,
                    ep.value,
                )
            except Exception:
                logger.warning(
                    "Failed to load agent entry-point '%s'",
                    ep.name,
                    exc_info=True,
                )

    @staticmethod
    def reset() -> None:
        """Clear all registrations (testing only)."""
        global _builtins_loaded  # noqa: PLW0603
        with _lock:
            _descriptors.clear()
            _builtins_loaded = False

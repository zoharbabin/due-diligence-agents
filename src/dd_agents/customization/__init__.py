"""User-editable agent customization (AD-1/AD-5).

One folder (``dd-config/``), one format (YAML front-matter + markdown body),
one merge rule (:func:`dd_agents.customization.loader._merge`). The loader is
pure: no LLM, no Click, no pipeline imports beyond ``models``.
"""

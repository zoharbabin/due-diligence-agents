"""Local sanctions and watchlist screening (Issue #274).

Official consolidated lists are downloaded on demand (``dd-agents screening
update``), parsed into a local index and matched on this machine, so the names
being screened never leave it. Users add their own lists under
``dd-config/screening/``.

Absence of a hit is never reported as clearance: a missing or stale list is a
coverage gap (see :mod:`dd_agents.screening.models`).
"""

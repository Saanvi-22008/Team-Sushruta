"""The deterministic safety core.

Every module here is PURE and config-driven: no LLM, no ML, no network, no I/O,
and no reads of the wall clock (the clock is always injected via a ``now``
argument). The same inputs always produce the same outputs. These are the
safety invariants of the system (see ``context.json`` key_patterns) and they are
proven by ``backend/tests/test_{trends,red_flags,staleness,rules_status,audit}.py``.
"""

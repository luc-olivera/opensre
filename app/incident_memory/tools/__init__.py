"""Incident-memory tool package (SRE-47 Phase 3).

Walked by OpenSRE's tool registry via ``register_external_tool_package`` (see
``app.incident_memory.register``). Each non-underscore submodule is imported and
any ``@tool``-decorated callables are picked up. Currently ships one tool:
``recall_similar_incidents`` (``recall.py``).
"""

from __future__ import annotations

"""
Role-Based Access Control (RBAC) for the Clinical Agent.

This module owns the *permission logic* (which role can do what) and the
LangGraph node that enforces it. The actual user storage (the SQLite `users`
table) lives in app.auth.users — this file is pure policy.

Design goals:
  - Zero-trust default: unknown user_id → GUEST → blocked.
  - Roles are additive permission sets, not subtract-from-admin lists.

Roles
------
ADMIN       full access; can query any drug topic + see admin dashboard
CLINICIAN   standard clinical access; drug interactions + FDA warnings
PATIENT     read-only, self-care queries only
GUEST       no access; every query is blocked
"""
from __future__ import annotations

import logging
import time
from typing import Literal

from app.auth.users import get_role, list_users, set_role
from app.models.schemas import AgentTrace, Role
from app.models.state import AgentState

logger = logging.getLogger(__name__)
AGENT_NAME = "access_control"


_PERMISSIONS: dict[Role, set[str]] = {
    Role.ADMIN: {"MEDICAL", "READ", "WRITE"},
    Role.CLINICIAN: {"MEDICAL", "READ"},
    Role.PATIENT: {"READ"},
    Role.GUEST: set(),
}


def has_permission(user_id: str, permission: Literal["MEDICAL", "READ", "WRITE"]) -> bool:
    role = get_role(user_id)
    return permission in _PERMISSIONS.get(role, set())


# Re-export so callers don't have to know about the users module.
register_user = set_role  # backward-compat alias for /admin/users POST handler
__all__ = ["register_user", "set_role", "get_role", "has_permission", "list_users", "access_control_node"]


# ── LangGraph node ────────────────────────────────────────────────────────────


def access_control_node(state: AgentState) -> dict:
    """
    Runs after input_guardrail, before orchestrator. Checks whether the
    authenticated user_id holds the MEDICAL permission. Fails closed:
    unknown users are GUEST and are immediately blocked.
    """
    if state.get("blocked"):
        return {}

    start_time = time.time()
    user_id = state.get("user_id") or "anonymous"
    role = get_role(user_id)
    allowed = has_permission(user_id, "MEDICAL")

    trace = AgentTrace(
        agent=AGENT_NAME,
        action="rbac_check",
        summary=f"user={user_id} role={role.value} permitted={allowed}",
        duration_seconds=round(time.time() - start_time, 4),
        metadata={"user_id": user_id, "role": role.value, "permitted": allowed},
    )
    logger.info("[%s] %s/%s permitted=%s", AGENT_NAME, user_id, role.value, allowed)

    if not allowed:
        return {
            "blocked": True,
            "block_reason": (
                f"Access denied. Your role '{role.value}' does not have MEDICAL permission. "
                "Contact your system administrator to request elevated access."
            ),
            "audit_log": [trace.model_dump()],
        }

    return {"audit_log": [trace.model_dump()]}

"""
Administrative endpoints — user management + audit log access for the admin panel.

In production these MUST sit behind an auth middleware (JWT / API key) so only
operators can call them. The handlers themselves trust their inputs.
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Query

from app.auth.users import list_users, set_role
from app.config.settings import settings
from app.models.schemas import RegisterUserRequest

router = APIRouter(prefix="/admin", tags=["admin"])


# ── User management ───────────────────────────────────────────────────────────


@router.post("/users", status_code=201)
def assign_role(req: RegisterUserRequest) -> dict:
    """Admin endpoint to change a user's role by user_id."""
    set_role(req.user_id, req.role)
    return {"user_id": req.user_id, "role": req.role}


@router.get("/users")
def get_users() -> list[dict]:
    """Full user list for the admin dashboard."""
    return list_users()


# ── Audit log access ──────────────────────────────────────────────────────────


def _read_audit_records() -> list[dict]:
    """Read every JSONL line from data/audit_logs/ — newest entries last."""
    audit_dir = Path(settings.AUDIT_LOG_DIR)
    if not audit_dir.exists():
        return []

    records: list[dict] = []
    for path in sorted(audit_dir.glob("*.jsonl")):
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return records


@router.get("/audit-logs")
def get_audit_logs(limit: int = Query(50, ge=1, le=500)) -> list[dict]:
    """Return the most recent `limit` audit log entries, newest first."""
    records = _read_audit_records()
    return list(reversed(records))[:limit]


@router.get("/stats")
def get_stats() -> dict:
    """Aggregate metrics over every audit log entry — feeds the admin dashboard."""
    records = _read_audit_records()
    total = len(records)
    blocked = sum(1 for r in records if r.get("blocked"))
    medical = sum(1 for r in records if r.get("is_medical"))
    errors = sum(1 for r in records if r.get("errors"))

    # Block reasons grouped by input/output security flag
    block_breakdown: dict[str, int] = {}
    for r in records:
        if r.get("blocked"):
            key = r.get("input_security_flag") or r.get("output_security_flag") or "ROUTER_BLOCK"
            block_breakdown[key] = block_breakdown.get(key, 0) + 1

    unique_users = len({r.get("user_id") for r in records if r.get("user_id")})
    total_evidence = sum(r.get("evidence_count", 0) for r in records)

    return {
        "total_queries": total,
        "blocked_queries": blocked,
        "allowed_queries": total - blocked,
        "medical_queries": medical,
        "queries_with_errors": errors,
        "unique_users": unique_users,
        "total_evidence_rows": total_evidence,
        "block_breakdown": block_breakdown,
    }

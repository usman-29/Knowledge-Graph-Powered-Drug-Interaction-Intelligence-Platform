"""
Append-only JSONL audit log for regulated workflows.

Every node contributes structured AgentTrace entries to state["audit_log"];
this terminal node persists the full trace plus any errors/warnings to
data/audit_logs/YYYYMMDD.jsonl so reviewers can reconstruct exactly *why*
a given answer was produced or blocked.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

from app.config.settings import settings
from app.models.schemas import AgentTrace
from app.models.state import AgentState

logger = logging.getLogger(__name__)
AGENT_NAME = "audit"

_AUDIT_DIR = Path(settings.AUDIT_LOG_DIR)


def _ensure_dir() -> Path:
    _AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    return _AUDIT_DIR


def audit_node(state: AgentState) -> dict:
    trace_id = state.get("trace_id", "unknown")
    record = {
        "trace_id": trace_id,
        "user_id": state.get("user_id"),
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "blocked": bool(state.get("blocked")),
        "block_reason": state.get("block_reason"),
        "input_security_flag": state.get("input_security_flag"),
        "output_security_flag": state.get("output_security_flag"),
        "is_medical": bool(state.get("is_medical")),
        "drugs_identified": state.get("drugs_identified") or [],
        "evidence_count": len(state.get("evidence") or []),
        "final_answer": state.get("final_answer"),
        "pipeline_trace": state.get("audit_log") or [],
        "errors": state.get("errors") or [],
        "warnings": state.get("warnings") or [],
    }

    try:
        path = _ensure_dir() / f"{datetime.utcnow().strftime('%Y%m%d')}.jsonl"
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, default=str) + "\n")
        persisted = True
        error: str | None = None
    except OSError as exc:
        persisted = False
        error = str(exc)
        logger.error("[%s] Failed to persist audit record: %s", AGENT_NAME, exc)

    trace = AgentTrace(
        agent=AGENT_NAME,
        action="persist_trace",
        summary=f"persisted={persisted}",
        error=error,
    )
    return {"audit_log": [trace.model_dump()]}

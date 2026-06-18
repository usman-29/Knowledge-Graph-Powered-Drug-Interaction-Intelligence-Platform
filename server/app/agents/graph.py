"""
LangGraph DAG — Autonomous Clinical Discharge & Care-Plan Orchestrator.

Security node execution order (all-or-nothing pass):

    START
      │
      ▼
    [input_guardrail]   ← Tier 1a — regex + LLM scan (PII, injection, jailbreak)
      │ blocked
      ├──────────────────► [safe_response] ──► [audit] ──► END
      │ clean
      ▼
    [access_control]    ← Tier 1b — RBAC: user_id → role → permission check
      │ denied
      ├──────────────────► [safe_response] ──► [audit] ──► END
      │ permitted
      ▼
    [orchestrator]      ← Tier 2  — intent routing: MEDICAL vs BLOCK
      │ BLOCK
      ├──────────────────► [safe_response] ──► [audit] ──► END
      │ MEDICAL
      ▼
    [medical_agent]     ← Tier 3  — bounded ReAct tool loop (Neo4j + openFDA)
      │
      ▼
    [risk_engine]       ← Tier 3a — deterministic, multi-domain risk arbitration.
      │                              Owns final_severity; LLM cannot downgrade.
      ▼
    [clinical_verifier] ← Tier 3b — three-pass safety reasoning:
      │                              Pass 0: deterministic rules engine (class-level)
      │                              Pass 1: per-claim evidence + direction + severity
      │                              Pass 2: holistic LLM (residual gaps + negative space)
      │ avg_score < 0 AND retry < 1
      ├──────────────────► [verification_retry] ──► [medical_agent]  (re-synthesis)
      │ otherwise
      ▼
    [output_guardrail]  ← Tier 4  — PII-egress + grounding + scope check
      │ blocked
      ├──────────────────► [audit] ──► END   (answer replaced with safe refusal)
      │ clean
      ▼
    [audit]             ← Append-only JSONL trace for compliance/explainability
      │
      ▼
     END
"""
from langchain_core.messages import HumanMessage
from langgraph.graph import StateGraph, END

from app.agents.clinical_verifier import clinical_verifier_node
from app.agents.medical_agent import medical_agent_node
from app.agents.orchestrator import orchestrator_node
from app.agents.risk_engine import risk_engine_node
from app.auth.rbac import access_control_node
from app.guardrails.input_guard import input_guardrail_node
from app.guardrails.output_guard import output_guardrail_node
from app.memory.audit import audit_node
from app.memory.checkpoint import get_checkpointer
from app.models.schemas import AgentTrace
from app.models.state import AgentState


_INTERNAL_REASON_MARKERS = (
    "crashed", "exception", "traceback", "unavailable", "timeout",
    "failing closed", "could not be validated",
)


def _sanitize_block_reason(reason: str | None) -> str:
    """Strip internal error / infrastructure text from a user-facing refusal.

    System-failure reasons ("router unavailable", "guardrail crashed",
    "could not be validated") collapse to a generic refusal. Clean policy
    verdicts ("Non-clinical query") pass through. Full text remains in
    the audit trace for review.
    """
    if not reason:
        return "This assistant only handles drug-safety and discharge-care questions."
    lowered = reason.lower()
    if any(marker in lowered for marker in _INTERNAL_REASON_MARKERS):
        return "This assistant only handles drug-safety and discharge-care questions."
    return reason


def _safe_response_node(state: AgentState) -> dict:
    """Terminal handler for any blocked path — returns a sanitised markdown refusal.

    The real block_reason (which may include exception text or router-failure
    detail) is preserved in the audit trace's `summary` field. The user-facing
    markdown shows only the sanitised reason; internal infrastructure errors
    never leak into the clinical output channel.
    """
    raw_reason = state.get("block_reason")
    user_reason = _sanitize_block_reason(raw_reason)
    markdown = (
        "# Request Blocked\n\n"
        f"{user_reason}\n\n"
        "---\n"
        "*If you believe this was blocked in error, please rephrase your question "
        "to focus on drug interactions, dosing, side effects, or discharge instructions.*"
    )
    trace = AgentTrace(
        agent="safe_response",
        action="render_refusal",
        summary=f"BLOCKED: {raw_reason or 'no reason given'}",
    )
    return {
        "final_answer": markdown,
        "audit_log": [trace.model_dump()],
    }


# Retry if avg verification score is net-negative; one corrective pass max.
_RETRY_SCORE_THRESHOLD = 0.0
_MAX_VERIFICATION_RETRIES = 1


# ── Verification retry node ───────────────────────────────────────────────────

def _verification_retry_node(state: AgentState) -> dict:
    """Inject contradiction context and reset synthesis outputs so medical_agent
    re-synthesises using the already-collected evidence (no new tool calls)."""
    results = state.get("verification_results") or []
    contradicted = [r for r in results if r.get("score") is not None and r["score"] < 0]

    claim_lines = "\n".join(
        f"  - [score {r['score']:+d}] {r['claim']}" for r in contradicted
    )
    retry_msg = HumanMessage(content=(
        "CORRECTION REQUEST: An independent clinical fact-checker found the following "
        "claims to be contradicted or unsupported by the retrieved evidence:\n\n"
        f"{claim_lines}\n\n"
        "Using ONLY the tool outputs already retrieved, remove or correct every claim "
        "listed above. Do NOT call any additional tools."
    ))

    retry_count = (state.get("verification_retry_count") or 0) + 1
    trace = AgentTrace(
        agent="verification_retry",
        action="inject_correction_context",
        summary=f"retry={retry_count}, contradicted_claims={len(contradicted)}",
    )
    return {
        "messages": [retry_msg],
        "final_answer": None,
        "safety_warnings": [],
        "verification_results": [],
        "verification_avg_score": None,
        "verification_retry_count": retry_count,
        "audit_log": [trace.model_dump()],
    }


# ── Routing functions ──────────────────────────────────────────────────────────

def _route_after_input(state: AgentState) -> str:
    return "safe_response" if state.get("blocked") else "access_control"


def _route_after_access(state: AgentState) -> str:
    return "safe_response" if state.get("blocked") else "orchestrator"


def _route_after_orchestrator(state: AgentState) -> str:
    if state.get("blocked") or not state.get("is_medical"):
        return "safe_response"
    return "medical_agent"


def _route_after_verifier(state: AgentState) -> str:
    avg = state.get("verification_avg_score")
    retry_count = state.get("verification_retry_count") or 0
    if (
        avg is not None
        and avg < _RETRY_SCORE_THRESHOLD
        and retry_count < _MAX_VERIFICATION_RETRIES
    ):
        return "verification_retry"
    return "output_guardrail"


# ── Graph assembly ─────────────────────────────────────────────────────────────

def build_graph(use_checkpointer: bool = True):
    g = StateGraph(AgentState)

    g.add_node("input_guardrail", input_guardrail_node)
    g.add_node("access_control", access_control_node)
    g.add_node("orchestrator", orchestrator_node)
    g.add_node("medical_agent", medical_agent_node)
    g.add_node("risk_engine", risk_engine_node)
    g.add_node("clinical_verifier", clinical_verifier_node)
    g.add_node("verification_retry", _verification_retry_node)
    g.add_node("output_guardrail", output_guardrail_node)
    g.add_node("safe_response", _safe_response_node)
    g.add_node("audit", audit_node)

    g.set_entry_point("input_guardrail")

    g.add_conditional_edges(
        "input_guardrail",
        _route_after_input,
        {"access_control": "access_control", "safe_response": "safe_response"},
    )
    g.add_conditional_edges(
        "access_control",
        _route_after_access,
        {"orchestrator": "orchestrator", "safe_response": "safe_response"},
    )
    g.add_conditional_edges(
        "orchestrator",
        _route_after_orchestrator,
        {"medical_agent": "medical_agent", "safe_response": "safe_response"},
    )
    g.add_edge("medical_agent", "risk_engine")
    g.add_edge("risk_engine", "clinical_verifier")
    g.add_conditional_edges(
        "clinical_verifier",
        _route_after_verifier,
        {"verification_retry": "verification_retry", "output_guardrail": "output_guardrail"},
    )
    g.add_edge("verification_retry", "medical_agent")
    g.add_edge("output_guardrail", "audit")
    g.add_edge("safe_response", "audit")
    g.add_edge("audit", END)

    if use_checkpointer:
        return g.compile(checkpointer=get_checkpointer())
    return g.compile()


_compiled_graph = None


def get_graph():
    """Lazy singleton — avoids opening the SQLite checkpoint file on import."""
    global _compiled_graph
    if _compiled_graph is None:
        _compiled_graph = build_graph()
    return _compiled_graph

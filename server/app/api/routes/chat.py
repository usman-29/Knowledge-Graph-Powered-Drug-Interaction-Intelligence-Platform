"""
Conversational entry point.

POST /chat runs a single turn through the LangGraph DAG. The `thread_id`
parameter lets a client resume a conversation — LangGraph's SqliteSaver
keeps the per-thread state and the audit log is appended on every turn.

When `patient_id` is provided, the patient's medication list and allergies
are prepended to the query as structured context so the medical agent can
reason about interactions with the patient's existing regimen.
"""
import uuid

from fastapi import APIRouter, HTTPException
from langchain_core.messages import HumanMessage

from app.agents.graph import get_graph
from app.db.patients import get_patient
from app.models.schemas import ChatRequest, FinalResponse, Patient

router = APIRouter(tags=["chat"])


def _build_patient_context(patient: Patient) -> str:
    """Render a compact, machine-readable preamble describing the patient's
    current state. The fixed [CLINICAL CONTEXT] / [END CONTEXT] markers let
    downstream guardrails recognize this as server-injected trusted data
    rather than user-typed PII."""
    meds = ", ".join(f"{m.name} {m.dose} {m.frequency}" for m in patient.medications) or "none"
    allergies = ", ".join(patient.allergies) or "none"
    conditions = ", ".join(patient.conditions) or "none"
    return (
        f"[CLINICAL CONTEXT — {patient.display_name}, {patient.age}{patient.sex}]\n"
        f"  Conditions: {conditions}\n"
        f"  Allergies:  {allergies}\n"
        f"  Current medications: {meds}\n"
        f"[END CONTEXT]\n\n"
    )


@router.post("/chat", response_model=FinalResponse)
def chat(req: ChatRequest) -> FinalResponse:
    graph = get_graph()
    trace_id = str(uuid.uuid4())
    thread_id = req.thread_id or trace_id

    query = req.query
    patient_payload: dict | None = None
    if req.patient_id:
        patient = get_patient(req.patient_id)
        if patient is None:
            raise HTTPException(status_code=404, detail=f"Patient {req.patient_id} not found")
        query = _build_patient_context(patient) + query
        # Pass the structured patient through state so the risk engine reads
        # age/conditions/allergies directly instead of re-parsing the prose
        # [CLINICAL CONTEXT] block the LLM sees.
        patient_payload = patient.model_dump()

    initial_state = {
        "messages": [HumanMessage(content=query)],
        "trace_id": trace_id,
        "user_id": req.user_id,
        "patient": patient_payload,
        "audit_log": [],
    }
    config = {"configurable": {"thread_id": thread_id}}

    try:
        result = graph.invoke(initial_state, config=config)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return FinalResponse(
        answer=result.get("final_answer") or "(no answer produced)",
        blocked=bool(result.get("blocked")),
        block_reason=result.get("block_reason"),
        trace_id=trace_id,
    )

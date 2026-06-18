from typing import Annotated, List, Optional, TypedDict, Dict, Any
from langchain_core.messages import BaseMessage
import operator


class AgentState(TypedDict, total=False):
    """
    Shared state across the LangGraph DAG.
    Every node reads/writes a slice — guardrails attach verdicts, the medical
    agent attaches evidence, and the audit node persists the final trace.
    """
    messages: Annotated[List[BaseMessage], operator.add]
    trace_id: str
    user_id: str

    is_medical: bool
    intent_reason: str

    drugs_identified: List[str]
    safety_warnings: List[str]
    evidence: List[Dict[str, Any]]

    # Server-injected patient context — populated by chat.py when patient_id is
    # set. The risk engine reads age/conditions/allergies from here so disease-
    # state and geriatric rules don't depend on the LLM parsing free-form text.
    patient: Optional[Dict[str, Any]]

    # Deterministic risk-engine output. Owns the canonical severity label; the
    # synthesis LLM only proposes a draft that arbitration overrides.
    risk_assessment: Optional[Dict[str, Any]]
    final_severity: Optional[str]

    # Per-claim fact-checking output from the clinical verifier node.
    # Each entry: {claim: str, score: int|None, reasoning: str, error: str|None}
    verification_results: List[Dict[str, Any]]
    # Average score across all scored claims (-2..+2); None when no claims were evaluated.
    verification_avg_score: Optional[float]
    # Number of corrective re-synthesis passes already performed (0 on first run).
    verification_retry_count: int

    input_security_flag: str
    output_security_flag: str
    pii_detected: bool
    injection_detected: bool
    hallucination_risk: str

    final_answer: Optional[str]
    blocked: bool
    block_reason: Optional[str]

    # Append-only collectors — every node may add entries; LangGraph merges via operator.add
    audit_log: Annotated[List[Dict[str, Any]], operator.add]
    errors: Annotated[List[str], operator.add]
    warnings: Annotated[List[str], operator.add]

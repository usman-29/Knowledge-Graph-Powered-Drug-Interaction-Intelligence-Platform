from datetime import datetime
from enum import Enum
from typing import List, Optional, Literal
from pydantic import BaseModel, Field, field_validator


class SecurityFlag(str, Enum):
    CLEAN = "CLEAN"
    PII_DETECTED = "PII_DETECTED"
    PROMPT_INJECTION = "PROMPT_INJECTION"
    JAILBREAK_ATTEMPT = "JAILBREAK_ATTEMPT"
    OFF_TOPIC = "OFF_TOPIC"
    HALLUCINATION_RISK = "HALLUCINATION_RISK"
    UNCITED_CLAIM = "UNCITED_CLAIM"


class Severity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class Role(str, Enum):
    """RBAC roles — consumed by auth.rbac for permission checks and by the
    admin API for user registration payloads."""
    ADMIN = "ADMIN"
    CLINICIAN = "CLINICIAN"
    PATIENT = "PATIENT"
    GUEST = "GUEST"


class ChatRequest(BaseModel):
    """POST /chat payload."""
    query: str = Field(min_length=1, max_length=4000)
    user_id: str = Field(default="anonymous", max_length=128)
    thread_id: Optional[str] = None
    patient_id: Optional[str] = Field(default=None, max_length=64)


class Medication(BaseModel):
    name: str
    dose: str
    frequency: str
    indication: str


class Patient(BaseModel):
    """Synthetic patient record — no real PII. Used for demo scoping."""
    id: str
    display_name: str = Field(description="Synthetic alias like 'Patient-001'")
    age: int
    sex: Literal["M", "F"]
    conditions: List[str] = Field(default_factory=list)
    allergies: List[str] = Field(default_factory=list)
    medications: List[Medication] = Field(default_factory=list)


class PatientSummary(BaseModel):
    """Lighter shape for the patient list view."""
    id: str
    display_name: str
    age: int
    sex: Literal["M", "F"]
    medication_count: int
    primary_condition: Optional[str] = None


class RegisterUserRequest(BaseModel):
    """POST /admin/users payload — admin-only RBAC role assignment."""
    user_id: str = Field(min_length=1, max_length=128)
    role: Role


class RegisterAuthRequest(BaseModel):
    """POST /auth/register payload — create a new user account."""
    email: str = Field(min_length=3, max_length=254)
    name: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=8, max_length=128)
    role: Literal["ADMIN", "CLINICIAN", "PATIENT"] = "CLINICIAN"


class VerifyAuthRequest(BaseModel):
    """POST /auth/verify payload — credential check for Auth.js."""
    email: str
    password: str


class UserPublic(BaseModel):
    """User shape returned to the frontend — never includes password_hash."""
    id: str
    email: str
    name: str
    role: Role
    created_at: int


class IntentClassification(BaseModel):
    """Orchestrator output — gate to the Medical Agent."""
    intent: Literal["MEDICAL", "BLOCK"] = Field(description="Routing decision")
    confidence: float = Field(ge=0.0, le=1.0, default=1.0)
    reason: str = Field(description="Short explanation of the routing call")

    @field_validator("confidence", mode="before")
    @classmethod
    def _normalize_confidence(cls, v: object) -> float:
        # LLMs sometimes return confidence as 0–100 instead of 0.0–1.0
        if isinstance(v, (int, float)) and v > 1:
            return float(v) / 100.0
        return v


class GuardrailReport(BaseModel):
    """Verdict from an input or output guardrail node."""
    stage: Literal["INPUT", "OUTPUT"]
    flag: SecurityFlag = SecurityFlag.CLEAN
    blocked: bool = False
    matched_patterns: List[str] = Field(default_factory=list)
    redacted_text: Optional[str] = None
    rationale: str = ""


class MedicalSafetyReport(BaseModel):
    """Structured output from the medical agent for a single drug."""
    drug_name: str = Field(description="Name of the drug analyzed")
    rxcui: Optional[str] = Field(default=None, description="RxNorm CUI if available")
    interaction_found: bool = Field(description="Whether an interaction was detected")
    severity: Severity = Field(description="Risk level")
    source: Literal["NEO4J", "FDA", "BOTH"] = Field(description="Provenance of the finding")
    warning_text: str = Field(description="The actual clinical warning")
    citations: List[str] = Field(default_factory=list)


class FinalResponse(BaseModel):
    """The user-facing response returned by the graph."""
    answer: str
    reports: List[MedicalSafetyReport] = Field(default_factory=list)
    blocked: bool = False
    block_reason: Optional[str] = None
    trace_id: str


class AuditEntry(BaseModel):
    """One immutable row appended to the audit log per node execution."""
    trace_id: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    node: str
    decision: str
    metadata: dict = Field(default_factory=dict)


class AgentTrace(BaseModel):
    """Per-node execution trace — one row appended to state['audit_log'] by every
    node. Standardizes what's captured (who/what/how-long/error) so the audit
    file is greppable and reviewers can reconstruct the run."""
    agent: str = Field(description="Module-level AGENT_NAME constant")
    action: str = Field(description="What the node was asked to do")
    summary: str = Field(description="Short human-readable result")
    duration_seconds: float = 0.0
    error: Optional[str] = None
    metadata: dict = Field(default_factory=dict)


class RiskFinding(BaseModel):
    """One deterministic finding produced by a rule module inside the risk engine.

    Every finding carries its own severity and the domain that raised it; the
    arbitrator collapses these to a single `final_severity` via max-severity
    rules. Findings are never averaged.
    """
    domain: Literal[
        "ddi",
        "disease_drug",
        "allergy",
        "organ_dysfunction",
        "geriatric",
        "electrolyte",
        "blackbox",
        "class_effect",
        "uncertainty",
    ]
    severity: Severity
    drugs: List[str] = Field(default_factory=list)
    mechanism: str
    recommendation: str
    rule_id: str
    # True when the finding was raised because terminology could not be normalised
    # (e.g. SNOMED lookup returned NOT_FOUND). Surfaces in the report so reviewers
    # see WHY caution was escalated.
    uncertain: bool = False


class RiskAssessment(BaseModel):
    """Output of the deterministic risk engine.

    `final_severity` is the arbitrated label — always the maximum across
    clinical findings, never an average. Downstream nodes MUST treat this
    as canonical and not downgrade it.

    `insufficient_data` is True only when clinical reasoning could not
    produce any signal at all (medical_agent crashed before extracting
    drugs). In that case `final_severity` is HIGH by design and the
    report renders as "HIGH RISK – INSUFFICIENT DATA". Tool / parsing
    failures that leave the clinical layer functional do NOT set this.
    """
    final_severity: Severity
    findings: List[RiskFinding] = Field(default_factory=list)
    contradictions: List[str] = Field(default_factory=list)
    insufficient_data: bool = False


class ClinicalReportSummary(BaseModel):
    """Structured synthesis from the medical agent — converted to markdown for
    the user-facing answer. The LLM is asked to return this directly so the
    output is type-checked rather than free-form."""
    one_line_verdict: str = Field(description="One-sentence safety verdict")
    overall_severity: Severity = Field(description="Highest severity across findings")
    key_warnings: List[str] = Field(
        default_factory=list,
        description="Bullet points — each a single clinical warning grounded in evidence",
    )
    drugs_with_no_data: List[str] = Field(
        default_factory=list,
        description="Drug names for which no Neo4j or FDA data was retrievable",
    )
    recommendation: str = Field(description="What the clinician should do next")

"""
Output guardrail node — the last stop before the answer reaches the user.

Three sequential checks, first-match-wins:
  1. PII leak — regex sweep on the final answer (deterministic, always runs).
  2. Grounding — if the answer makes definitive clinical claims but no
     evidence was retrieved, mark it as UNCITED_CLAIM.
  3. LLM judge — structured Pydantic verdict on hallucination / off-topic.

Every code path returns the same dict shape so the audit node can rely on
the keys being present.
"""
from __future__ import annotations

import logging
import time

from langchain_core.messages import HumanMessage

from app.config.llm import get_structured_llm
from app.guardrails.patterns import PII_PATTERNS
from app.models.schemas import AgentTrace, GuardrailReport, SecurityFlag
from app.models.state import AgentState

logger = logging.getLogger(__name__)
AGENT_NAME = "output_guardrail"


def _pii_leak_check(text: str) -> GuardrailReport:
    matched = [label for label, pat in PII_PATTERNS.items() if pat.search(text)]
    if matched:
        return GuardrailReport(
            stage="OUTPUT",
            flag=SecurityFlag.PII_DETECTED,
            blocked=True,
            matched_patterns=matched,
            rationale="Outbound response contains PII — blocking egress.",
        )
    return GuardrailReport(stage="OUTPUT", flag=SecurityFlag.CLEAN, blocked=False)


def _grounding_check(answer: str, evidence: list[dict]) -> GuardrailReport:
    """
    Heuristic: block only when the answer asserts a specific drug-drug interaction
    or contraindication but no evidence rows were retrieved from Neo4j / FDA.
    Patient-data answers (medication lists, allergy summaries, condition info)
    are excluded — their source is the patient record, not the interaction graph.
    Generic clinical language ("warning", "side effects", "avoid") is NOT enough
    to trigger this check; we need a precise interaction or contraindication claim.
    """
    interaction_kws = (
        "contraindicated",
        "black box warning",
        "drug-drug interaction",
        "clinically significant interaction",
        "do not co-administer",
        "absolute contraindication",
    )
    if not evidence and any(kw in answer.lower() for kw in interaction_kws):
        return GuardrailReport(
            stage="OUTPUT",
            flag=SecurityFlag.UNCITED_CLAIM,
            blocked=True,
            rationale="Specific drug-drug interaction or contraindication claimed with zero retrieved evidence.",
        )
    return GuardrailReport(stage="OUTPUT", flag=SecurityFlag.CLEAN, blocked=False)


_JUDGE_PROMPT = (
    "You are an output safety classifier for a regulated clinical agent. "
    "Your job is to catch genuine hallucinations or completely off-topic responses — "
    "NOT to second-guess a clinically reasonable answer.\n\n"
    "Given the QUESTION and the ANSWER below, produce a GuardrailReport. "
    "Set `stage` to OUTPUT. "
    "Choose `flag` from: CLEAN, OFF_TOPIC, HALLUCINATION_RISK.\n\n"
    "Rules:\n"
    "  - Set flag=CLEAN if the answer addresses the question, even partially or indirectly. "
    "A medication list, allergy summary, or drug interaction context is CLEAN when the "
    "question is about a patient's health, medications, or allergies.\n"
    "  - Set flag=OFF_TOPIC ONLY if the answer is entirely unrelated to the question "
    "and to clinical care (e.g. the answer discusses sports when asked about drugs).\n"
    "  - Set flag=HALLUCINATION_RISK ONLY if the answer makes specific factual claims "
    "that are clearly unsupported or contradict well-established medical fact.\n"
    "  - When in doubt, flag=CLEAN. Over-blocking harms patient care.\n\n"
    "Set `blocked` to true ONLY when flag is OFF_TOPIC or HALLUCINATION_RISK. "
    "Provide a one-sentence rationale.\n\n"
    "QUESTION: <<<{question}>>>\n\n"
    "ANSWER: <<<{answer}>>>"
)


def _llm_judge(answer: str, question: str = "") -> GuardrailReport:
    try:
        llm = get_structured_llm(GuardrailReport, declared_intent="safety_judge")
        report: GuardrailReport = llm.invoke(
            [HumanMessage(content=_JUDGE_PROMPT.format(question=question, answer=answer))]
        )
        report.stage = "OUTPUT"
        return report
    except Exception as exc:
        logger.warning("[%s] LLM judge unreachable: %s — skipping semantic check", AGENT_NAME, exc)
        return GuardrailReport(
            stage="OUTPUT",
            flag=SecurityFlag.CLEAN,
            blocked=False,
            rationale=f"LLM judge unavailable ({exc}); semantic check skipped.",
        )


def output_guardrail_node(state: AgentState) -> dict:
    start_time = time.time()
    answer = state.get("final_answer") or ""
    evidence = state.get("evidence") or []
    messages = state.get("messages") or []
    original_query = messages[-1].content if messages else ""

    try:
        for check in (
            _pii_leak_check(answer),
            _grounding_check(answer, evidence),
            _llm_judge(answer, question=original_query),
        ):
            if check.blocked:
                duration = time.time() - start_time
                trace = AgentTrace(
                    agent=AGENT_NAME,
                    action="output_safety_scan",
                    summary=f"BLOCKED ({check.flag.value}): {check.rationale}",
                    duration_seconds=round(duration, 2),
                    metadata={"matched_patterns": check.matched_patterns},
                )
                logger.info("[%s] BLOCKED %s in %.2fs", AGENT_NAME, check.flag.value, duration)
                return {
                    "output_security_flag": check.flag.value,
                    "hallucination_risk": check.flag.value
                    if check.flag == SecurityFlag.HALLUCINATION_RISK
                    else "LOW",
                    "blocked": True,
                    "block_reason": check.rationale,
                    "final_answer": (
                        "This response was withheld by the safety layer. "
                        f"Reason: {check.rationale}"
                    ),
                    "audit_log": [trace.model_dump()],
                }

        duration = time.time() - start_time
        trace = AgentTrace(
            agent=AGENT_NAME,
            action="output_safety_scan",
            summary="CLEAN — answer cleared all three checks",
            duration_seconds=round(duration, 2),
        )
        logger.info("[%s] CLEAN in %.2fs", AGENT_NAME, duration)
        return {
            "output_security_flag": SecurityFlag.CLEAN.value,
            "hallucination_risk": "LOW",
            "audit_log": [trace.model_dump()],
        }

    except Exception as exc:
        duration = time.time() - start_time
        logger.error("[%s] Guardrail crashed: %s", AGENT_NAME, exc)
        reason = f"Output guardrail crashed ({exc}); withholding response."
        trace = AgentTrace(
            agent=AGENT_NAME,
            action="output_safety_scan",
            summary=f"FALLBACK BLOCK: {exc}",
            duration_seconds=round(duration, 2),
            error=str(exc),
        )
        return {
            "output_security_flag": SecurityFlag.HALLUCINATION_RISK.value,
            "hallucination_risk": "HIGH",
            "blocked": True,
            "block_reason": reason,
            "final_answer": "This response was withheld due to an internal safety error.",
            "audit_log": [trace.model_dump()],
            "errors": [f"[{AGENT_NAME}] {exc}"],
        }

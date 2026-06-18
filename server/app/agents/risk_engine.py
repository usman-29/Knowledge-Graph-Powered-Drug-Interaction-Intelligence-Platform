"""
Deterministic risk engine — sits between medical_agent and clinical_verifier.

Owns the canonical risk label. Aggregates findings from independent
clinical domains and arbitrates by max-severity so one severe
contraindication dominates many neutral DDI results.

Domains evaluated (all run, none are skipped on a hit):

  1. Class-effect / DDI / electrolyte → rules.class_effects
  2. Disease-drug contraindications   → rules.disease_drug
  3. Allergy + cross-reactivity       → rules.allergy
  4. Organ dysfunction                → rules.organ_dysfunction
  5. Geriatric (Beers)                → rules.beers_criteria
  6. Black-box amplification          → rules.blackbox_amplifier

Hard separation guarantees:

  - Clinical signal ONLY: tool / parsing / metadata failures do NOT
    influence the risk label. Pharmacology rules run on drug names and
    patient state, both of which survive tool outages.
  - When clinical reasoning could not produce ANY signal — i.e. the
    medical_agent crashed before extracting drugs — the engine returns
    HIGH with `insufficient_data=True`, rendered as
    "HIGH RISK – INSUFFICIENT DATA". This is the only path that returns
    HIGH without a matching clinical finding.
  - System errors, trace IDs, and internal scoring annotations never
    appear in the user-facing report; they are written to the audit
    trace metadata only.
"""
from __future__ import annotations

import logging
import time

from app.agents import arbitration
from app.agents.rules import (
    allergy,
    beers_criteria,
    blackbox_amplifier,
    class_effects,
    disease_drug,
    organ_dysfunction,
)
from app.models.schemas import AgentTrace, RiskFinding, Severity
from app.models.state import AgentState

logger = logging.getLogger(__name__)
AGENT_NAME = "risk_engine"


def risk_engine_node(state: AgentState) -> dict:
    if state.get("blocked"):
        return {}

    start = time.time()
    drugs    = state.get("drugs_identified") or []
    patient  = state.get("patient")
    evidence = state.get("evidence") or []
    warnings = state.get("safety_warnings") or []
    draft    = state.get("final_answer") or ""
    errors   = state.get("errors") or []

    findings: list[RiskFinding] = []
    findings.extend(class_effects.evaluate(drugs, patient))
    findings.extend(disease_drug.evaluate(drugs, patient))
    findings.extend(allergy.evaluate(drugs, patient))
    findings.extend(organ_dysfunction.evaluate(drugs, patient))
    findings.extend(beers_criteria.evaluate(drugs, patient))
    findings.extend(blackbox_amplifier.evaluate(drugs, patient, evidence))

    # Contradiction surface: only the medical_agent report + safety_warnings.
    # The synthesis fallback prose now uses clinically neutral language, so
    # this only catches genuine clinical signals (renal impairment, BBW, …).
    narrative = draft + "\n" + "\n".join(warnings)

    # Insufficient-data signal — the strict separation between system
    # failure and clinical uncertainty. Set only when reasoning truly
    # could not produce a clinical signal: medical_agent erred AND we
    # have no drugs to evaluate. Tool failures that still let rules
    # run (drugs were extracted) do NOT trigger this.
    medical_agent_failed = any(e.startswith("[medical_agent]") for e in errors)
    insufficient_clinical_data = medical_agent_failed and not drugs

    assessment = arbitration.arbitrate(
        findings,
        narrative_text=narrative,
        insufficient_clinical_data=insufficient_clinical_data,
    )

    updated_answer = _inject_assessment_into_report(draft, assessment)

    duration = round(time.time() - start, 2)
    # The trace metadata is internal-only — it captures rule_ids,
    # contradictions, and the insufficient_data flag for audit. Never
    # rendered to the user.
    trace = AgentTrace(
        agent=AGENT_NAME,
        action="risk_arbitration",
        summary=(
            f"final={assessment.final_severity.value}, "
            f"findings={len(assessment.findings)}, "
            f"contradictions={len(assessment.contradictions)}, "
            f"insufficient_data={assessment.insufficient_data}"
        ),
        duration_seconds=duration,
        metadata={
            "final_severity":     assessment.final_severity.value,
            "insufficient_data":  assessment.insufficient_data,
            "contradictions":     assessment.contradictions,
            "findings":           [f.model_dump() for f in assessment.findings],
        },
    )
    logger.info(
        "[%s] %s in %.2fs (%d findings, insufficient_data=%s)",
        AGENT_NAME, assessment.final_severity.value, duration,
        len(assessment.findings), assessment.insufficient_data,
    )

    return {
        "risk_assessment": assessment.model_dump(),
        "final_severity":  assessment.final_severity.value,
        "final_answer":    updated_answer,
        "audit_log":       [trace.model_dump()],
    }


# ── Report rewriter ───────────────────────────────────────────────────────────

_SEVERITY_LABEL = {
    Severity.LOW:      "Low Risk",
    Severity.MEDIUM:   "Moderate Risk",
    Severity.HIGH:     "High Risk",
    Severity.CRITICAL: "Critical Risk",
}
_SEVERITY_BADGE = {
    Severity.LOW:      "🟢",
    Severity.MEDIUM:   "🟡",
    Severity.HIGH:     "🟠",
    Severity.CRITICAL: "🔴",
}
_DOMAIN_LABEL = {
    "ddi":               "Drug-drug interaction",
    "disease_drug":      "Disease contraindication",
    "allergy":           "Allergy / cross-reactivity",
    "organ_dysfunction": "Organ dysfunction",
    "geriatric":         "Geriatric (Beers)",
    "electrolyte":       "Electrolyte / physiologic",
    "blackbox":          "FDA boxed warning",
    "class_effect":      "Drug-class effect",
    "uncertainty":       "Uncertainty / data gap",
}


def _severity_label(assessment) -> str:
    """Render the severity label. HIGH + insufficient_data gets the explicit
    "HIGH RISK – INSUFFICIENT DATA" treatment per the safety fallback rule."""
    base = _SEVERITY_LABEL.get(assessment.final_severity, assessment.final_severity.value)
    if assessment.insufficient_data:
        return f"{base} – Insufficient Data"
    return base


def _arbitrated_verdict(assessment) -> str:
    """Deterministic one-line verdict derived from the top finding.

    Replaces the LLM-written one_line_verdict so the user-facing summary
    never says "no concerns" while the Risk Level badge is HIGH.
    """
    if assessment.insufficient_data:
        return (
            "HIGH RISK — INSUFFICIENT DATA. Manual clinician review is "
            "required before any prescribing decision."
        )
    if not assessment.findings:
        return (
            "No drug-safety concerns identified in the available data. "
            "Verify the patient context before prescribing."
        )
    top = assessment.findings[0]
    severity = _SEVERITY_LABEL.get(top.severity, top.severity.value)
    drugs = ", ".join(top.drugs) if top.drugs else "this regimen"
    mech = (top.mechanism or "").split(". ")[0].strip().rstrip(".")
    if len(mech) > 180:
        mech = mech[:177] + "…"
    extra = ""
    if len(assessment.findings) > 1:
        extra = f" {len(assessment.findings) - 1} additional finding(s) — see below."
    return f"{severity}: {drugs} — {mech}.{extra}"


def _replace_clinical_assessment(text: str, verdict: str) -> str:
    """Replace the line under `## Clinical Assessment` with the arbitrated
    verdict. No-op when the header is missing."""
    if not text:
        return text
    lines = text.split("\n")
    for i, line in enumerate(lines):
        if line.strip() == "## Clinical Assessment":
            # The header is followed by an empty line, then the LLM verdict
            # paragraph. Replace the first non-empty line after the header.
            for j in range(i + 1, len(lines)):
                if lines[j].strip():
                    lines[j] = verdict
                    return "\n".join(lines)
            return text
    return text


def _inject_assessment_into_report(report_md: str, assessment) -> str:
    """Rewrite the medical-agent draft so it reflects the arbitrated severity
    and append the clinical-findings table.

    Two surgical rewrites:
      1. The "| Risk Level |" row in the header table.
      2. The verdict paragraph under "## Clinical Assessment" — so the LLM
         can't write "no major concerns" under a HIGH label.
    """
    label = _severity_label(assessment)
    badge = _SEVERITY_BADGE.get(assessment.final_severity, "⚪")
    verdict = _arbitrated_verdict(assessment)

    new_row = f"| **Risk Level** | {badge} {label} |"
    rewritten, replaced = _replace_first_risk_row(report_md, new_row)
    if not replaced and report_md:
        rewritten = report_md + f"\n\n**Risk Level:** {badge} {label}\n"
    elif not report_md:
        rewritten = f"**Risk Level:** {badge} {label}\n"

    rewritten = _replace_clinical_assessment(rewritten, verdict)

    return rewritten + _render_risk_section(assessment)


def _replace_first_risk_row(text: str, new_row: str) -> tuple[str, bool]:
    if not text:
        return text, False
    lines = text.split("\n")
    for i, line in enumerate(lines):
        if line.startswith("| **Risk Level**"):
            lines[i] = new_row
            return "\n".join(lines), True
    return text, False


def _render_risk_section(assessment) -> str:
    """User-facing clinical findings table.

    Renders only the clinical content (severity, domain, drugs, mechanism).
    No rule_ids, no contradictions list, no internal annotations — those
    live in the audit metadata, not in the clinician's report.
    """
    if assessment.insufficient_data:
        return (
            "\n\n---\n\n"
            "## Comprehensive Risk Assessment\n\n"
            "> The clinical-safety engine could not evaluate this request "
            "with the available data. Manual clinician review is required "
            "before any prescribing decision.\n"
        )

    if not assessment.findings:
        return ""

    parts: list[str] = ["", "---", "", "## Comprehensive Risk Assessment", ""]
    parts.append("| Severity | Domain | Drugs | Mechanism |")
    parts.append("| --- | --- | --- | --- |")
    for f in assessment.findings:
        sev_badge = _SEVERITY_BADGE.get(f.severity, "⚪")
        domain    = _DOMAIN_LABEL.get(f.domain, f.domain)
        drugs     = ", ".join(f.drugs) if f.drugs else "—"
        mech      = (f.mechanism or "").replace("|", "\\|").replace("\n", " ")
        if len(mech) > 220:
            mech = mech[:217] + "…"
        parts.append(
            f"| {sev_badge} {f.severity.value} | {domain} | {drugs} | {mech} |"
        )
    parts.append("")
    return "\n".join(parts)

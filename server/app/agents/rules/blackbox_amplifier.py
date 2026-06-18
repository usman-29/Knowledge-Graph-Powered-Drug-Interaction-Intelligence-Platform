"""Black-box warning amplifier.

The medical agent's tool layer fetches FDA boxed warnings as evidence rows
([`get_fda_blackbox_warning`](app/tools/medical_tools.py)). This rule
inspects those evidence rows and:

  1. Always emits at least MODERATE when a real boxed warning is present
     (so the synthesis LLM can't downgrade a BBW finding to LOW).
  2. Escalates to HIGH when the patient is "vulnerable" — elderly, CKD,
     HF, liver disease, or pregnant — because boxed-warning risks are
     disproportionately realised in those populations.
"""
from __future__ import annotations

from typing import Any

from app.agents.rules import _patient as P
from app.models.schemas import RiskFinding, Severity


# Markers in the openFDA response body that confirm a real boxed warning
# (as opposed to the "No FDA boxed warning on file" fall-through string).
_BBW_PRESENT_MARKERS = ("FDA boxed warning:",)
_BBW_ABSENT_MARKERS  = (
    "No FDA boxed warning on file",
    "No specific warning found",
    "FDA lookup unavailable",
)


def evaluate(
    drugs: list[str],
    patient: dict[str, Any] | None,
    evidence: list[dict],
) -> list[RiskFinding]:
    findings: list[RiskFinding] = []
    vulnerable = P.is_vulnerable(patient)

    for row in evidence or []:
        if row.get("tool") != "get_fda_blackbox_warning":
            continue
        result = (row.get("result") or "")
        if any(m in result for m in _BBW_ABSENT_MARKERS):
            continue
        if not any(m in result for m in _BBW_PRESENT_MARKERS):
            continue

        rxcui = (row.get("args") or {}).get("rxcui") or "—"
        snippet = result.split("FDA boxed warning:", 1)[-1].strip()[:300]

        if vulnerable:
            findings.append(RiskFinding(
                domain="blackbox",
                severity=Severity.HIGH,
                drugs=[f"RxCUI {rxcui}"],
                mechanism=(
                    "FDA boxed warning present and the patient has at least "
                    "one risk factor (elderly, CKD, HF, liver disease, or "
                    f"pregnancy) that elevates exposure to the warned harm: "
                    f"{snippet}"
                ),
                recommendation=(
                    "Confirm the indication is essential, document informed "
                    "consent of the boxed risk, and put in place the "
                    "monitoring named in the warning."
                ),
                rule_id="BBW_VULNERABLE_PATIENT",
            ))
        else:
            findings.append(RiskFinding(
                domain="blackbox",
                severity=Severity.MEDIUM,
                drugs=[f"RxCUI {rxcui}"],
                mechanism=(
                    "FDA boxed warning is on file for this medication: "
                    f"{snippet}"
                ),
                recommendation=(
                    "Review the boxed warning with the patient and verify "
                    "the prescribed monitoring plan."
                ),
                rule_id="BBW_PRESENT",
            ))

    return findings

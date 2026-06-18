"""Organ-dysfunction risk rules.

Captures drug risks driven by impaired renal/hepatic clearance or by the
physiology of heart failure, when the DDI database can't see them. These
overlap with disease_drug.py at the edges; the split is intentional:

  disease_drug    → "this drug should not be given to a patient with X"
  organ_dysfunction → "this drug needs dose adjustment / extra monitoring
                       because organ X cannot clear or tolerate it"

Both can fire for the same drug+condition pair without double-counting,
because arbitration deduplicates by rule_id.
"""
from __future__ import annotations

from typing import Any

from app.agents import ontology
from app.agents.rules import _patient as P
from app.models.schemas import RiskFinding, Severity


# Drugs requiring renal dose adjustment in CKD. Severity is MEDIUM by default —
# the issue is dosing, not absolute contraindication.
_RENAL_DOSE_SENSITIVE = {
    "digoxin", "gabapentin", "pregabalin", "lithium", "allopurinol",
    "atenolol", "ranitidine", "famotidine", "ciprofloxacin", "levofloxacin",
    "vancomycin", "enoxaparin", "dabigatran", "rivaroxaban", "apixaban",
    "edoxaban", "metformin", "spironolactone",
}

_HEPATOTOXIC = {
    "acetaminophen", "isoniazid", "rifampin", "valproic acid", "valproate",
    "methotrexate", "amiodarone", "ketoconazole", "fluconazole",
    "amoxicillin-clavulanate", "augmentin", "nitrofurantoin", "azathioprine",
    "atorvastatin", "simvastatin", "rosuvastatin", "lovastatin", "pravastatin",
}

# Drugs that worsen HF physiology beyond NSAIDs (which are caught in disease_drug)
_HF_WORSENING = {
    "diltiazem", "verapamil", "pioglitazone", "rosiglitazone",
    "itraconazole",
}


def _norm(s: str) -> str:
    return (s or "").lower().strip()


def evaluate(drugs: list[str], patient: dict[str, Any] | None) -> list[RiskFinding]:
    findings: list[RiskFinding] = []
    drug_set = {_norm(d): d for d in drugs}

    # ── CKD — renal dose-adjustment risk ──────────────────────────────────────
    if P.has_ckd(patient):
        hits = [orig for n, orig in drug_set.items() if n in _RENAL_DOSE_SENSITIVE]
        if hits:
            findings.append(RiskFinding(
                domain="organ_dysfunction",
                severity=Severity.MEDIUM,
                drugs=hits,
                mechanism=(
                    "Renal clearance is reduced in CKD; these agents need "
                    "eGFR-based dose adjustment or accumulate to toxic levels."
                ),
                recommendation=(
                    "Confirm current eGFR and apply CKD-adjusted dosing per "
                    "the package insert. Recheck levels for narrow-TI agents "
                    "(digoxin, lithium) after any dose change."
                ),
                rule_id="CKD_RENAL_DOSING",
            ))

        # Digoxin specifically — toxicity risk dominates and warrants HIGH
        if "digoxin" in drug_set:
            findings.append(RiskFinding(
                domain="organ_dysfunction",
                severity=Severity.HIGH,
                drugs=[drug_set["digoxin"]],
                mechanism=(
                    "Digoxin is renally cleared with a narrow therapeutic "
                    "index. In CKD, accumulation produces nausea, visual "
                    "disturbances, and life-threatening arrhythmias."
                ),
                recommendation=(
                    "Reduce dose by 25-50% and check serum digoxin within "
                    "5–7 days. Maintain K+ >4.0 and Mg2+ >2.0 to reduce "
                    "arrhythmia risk."
                ),
                rule_id="DIGOXIN_CKD_TOXICITY",
            ))

    # ── Liver disease — hepatotoxicity ────────────────────────────────────────
    if P.has_liver_disease(patient):
        hits = [orig for n, orig in drug_set.items() if n in _HEPATOTOXIC]
        if hits:
            findings.append(RiskFinding(
                domain="organ_dysfunction",
                severity=Severity.HIGH,
                drugs=hits,
                mechanism=(
                    "Hepatic metabolism is impaired; these agents have known "
                    "hepatotoxicity that compounds underlying liver disease."
                ),
                recommendation=(
                    "Check baseline LFTs, dose-adjust per Child-Pugh score, "
                    "and substitute non-hepatotoxic alternatives where "
                    "possible. Monitor LFTs at 2 and 8 weeks."
                ),
                rule_id="LIVER_DISEASE_HEPATOTOXIC",
            ))

    # ── Heart failure — agents that worsen HF physiology ──────────────────────
    if P.has_heart_failure(patient):
        hits = [orig for n, orig in drug_set.items() if n in _HF_WORSENING]
        if hits:
            findings.append(RiskFinding(
                domain="organ_dysfunction",
                severity=Severity.HIGH,
                drugs=hits,
                mechanism=(
                    "These agents have negative inotropic, fluid-retaining, or "
                    "cardiotoxic effects that decompensate heart failure."
                ),
                recommendation=(
                    "Avoid in HFrEF. If clinically essential, use the lowest "
                    "dose with frequent weight, BNP, and echocardiogram "
                    "follow-up."
                ),
                rule_id="HF_WORSENING_AGENT",
            ))

    return findings

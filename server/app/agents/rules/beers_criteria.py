"""Beers Criteria — potentially inappropriate medications in adults ≥65.

This is a curated subset focused on the high-impact categories from the
2023 AGS update:

  - Benzodiazepines & Z-drugs (falls, cognition)
  - First-generation antihistamines (anticholinergic burden)
  - Tricyclic antidepressants (anticholinergic burden, orthostasis)
  - Muscle relaxants with anticholinergic effect
  - NSAIDs (GI/cardiac/renal risk amplified with age)
  - Sulfonylureas (hypoglycaemia)
  - Digoxin >0.125 mg/day proxy — handled in organ_dysfunction.py

Each rule fires only when age ≥65; severity is MODERATE by default and
escalates to HIGH when paired with an aggravating condition (e.g. NSAID
in an elderly CKD patient is HIGH there, MODERATE here — arbitration
keeps the max).
"""
from __future__ import annotations

from typing import Any

from app.agents import ontology
from app.agents.rules import _patient as P
from app.models.schemas import RiskFinding, Severity


def evaluate(drugs: list[str], patient: dict[str, Any] | None) -> list[RiskFinding]:
    if not P.is_elderly(patient):
        return []

    findings: list[RiskFinding] = []
    age = P.age_of(patient)

    def _add(cls: str, severity: Severity, mechanism: str, recommendation: str, rule_id: str) -> None:
        hits = ontology.drugs_in_class(drugs, cls)
        if hits:
            findings.append(RiskFinding(
                domain="geriatric",
                severity=severity,
                drugs=hits,
                mechanism=f"[Beers Criteria, age {age}] {mechanism}",
                recommendation=recommendation,
                rule_id=rule_id,
            ))

    _add(
        "benzodiazepine",
        Severity.HIGH,
        "Benzodiazepines increase the risk of falls, fractures, and "
        "delirium in older adults; cognitive sensitivity is heightened.",
        "Avoid for insomnia, agitation, or delirium. If needed for "
        "alcohol withdrawal or end-of-life care, use the lowest dose "
        "with frequent reassessment.",
        "BEERS_BENZODIAZEPINE",
    )
    _add(
        "z_drug",
        Severity.MEDIUM,
        "Zolpidem and related Z-drugs cause delirium, falls, and minimal "
        "sleep-quality benefit in older adults.",
        "Avoid for chronic use. Prefer behavioural sleep interventions; "
        "limit to short-term use if pharmacotherapy is essential.",
        "BEERS_Z_DRUG",
    )
    _add(
        "first_gen_antihistamine",
        Severity.MEDIUM,
        "Strongly anticholinergic — causes confusion, urinary retention, "
        "dry mouth, and constipation in the elderly.",
        "Substitute a non-anticholinergic agent (loratadine, cetirizine) "
        "or discontinue if used for sleep.",
        "BEERS_FIRST_GEN_ANTIHISTAMINE",
    )
    _add(
        "tricyclic_antidepressant",
        Severity.HIGH,
        "TCAs combine anticholinergic effect, sedation, and orthostatic "
        "hypotension — high fall risk in older adults.",
        "Avoid as first-line. Switch to SSRI/SNRI for depression or "
        "duloxetine/gabapentin for neuropathic pain.",
        "BEERS_TCA",
    )
    _add(
        "muscle_relaxant_anticholinergic",
        Severity.MEDIUM,
        "Centrally acting muscle relaxants are anticholinergic and "
        "sedating; effectiveness is questionable in older adults.",
        "Discontinue. For musculoskeletal pain, prefer acetaminophen "
        "plus physical therapy.",
        "BEERS_MUSCLE_RELAXANT",
    )
    _add(
        "nsaid",
        Severity.MEDIUM,
        "Chronic NSAID use in older adults increases GI bleeding, AKI, "
        "and HF decompensation. Risk amplifies with concomitant "
        "anticoagulant, ACE/ARB, or diuretic therapy.",
        "Use the shortest course at the lowest dose. Prefer "
        "acetaminophen or topical NSAIDs. Add a PPI when chronic use "
        "is unavoidable.",
        "BEERS_NSAID",
    )

    # ── Sulfonylureas (glyburide especially) — prolonged hypoglycaemia ───────
    sulfonylurea_hits = ontology.drugs_in_class(drugs, "sulfonylurea")
    if sulfonylurea_hits:
        is_glyburide = any("glyburide" in (d or "").lower() for d in sulfonylurea_hits)
        findings.append(RiskFinding(
            domain="geriatric",
            severity=Severity.HIGH if is_glyburide else Severity.MEDIUM,
            drugs=sulfonylurea_hits,
            mechanism=(
                f"[Beers Criteria, age {age}] Sulfonylureas — especially "
                "glyburide — cause prolonged hypoglycaemia in older adults."
            ),
            recommendation=(
                "Avoid glyburide. Prefer glipizide if a sulfonylurea is needed, "
                "or switch to a DPP-4 inhibitor or basal insulin."
            ),
            rule_id="BEERS_SULFONYLUREA",
        ))

    return findings

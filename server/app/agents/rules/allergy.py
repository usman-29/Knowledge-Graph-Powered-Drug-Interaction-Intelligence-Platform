"""Allergy + cross-reactivity rules.

Two checks per patient allergy:

  1. Direct exposure — a drug in the regimen IS the allergen (or a
     synonym maps to it).
  2. Cross-reactive exposure — a drug belongs to a class clinically
     associated with the allergen (NSAIDs ⇄ aspirin, penicillin ⇄
     cephalosporin partial overlap, iodinated contrast cluster).

Unmappable allergy terms (SNOMED miss, no synonym) escalate as an
uncertainty finding rather than passing silently — requirement #5.
"""
from __future__ import annotations

from typing import Any

from app.agents import ontology
from app.models.schemas import RiskFinding, Severity


# class membership → canonical allergy agent it cross-reacts with
_CROSS_REACTIVITY: dict[str, str] = {
    "nsaid":      "aspirin",
    "aspirin":    "nsaid",          # any salicylate exposure triggers NSAID allergy
    "penicillin": "cephalosporin",  # ~1-5% partial cross-reactivity
}


def evaluate(drugs: list[str], patient: dict[str, Any] | None) -> list[RiskFinding]:
    allergies = list((patient or {}).get("allergies") or [])
    if not allergies:
        return []

    findings: list[RiskFinding] = []
    exposure_agents = ontology.expand_exposure_to_agents(drugs)

    for raw in allergies:
        match = ontology.normalise_allergy(raw)

        # ── Uncertainty: terminology couldn't be normalised ──────────────────
        if match.canonical is None:
            findings.append(RiskFinding(
                domain="uncertainty",
                severity=Severity.MEDIUM,
                drugs=[],
                mechanism=(
                    f"Allergy term '{raw}' could not be mapped to a known "
                    "agent. Cross-reactivity with the current regimen cannot "
                    "be ruled out."
                ),
                recommendation=(
                    "Clarify the allergen with the patient and document the "
                    "reaction type before continuing this regimen."
                ),
                rule_id="ALLERGY_UNMAPPED",
                uncertain=True,
            ))
            continue

        canonical = match.canonical

        # ── Direct exposure ──────────────────────────────────────────────────
        if canonical in exposure_agents:
            exposed = _drugs_for_agent(drugs, canonical)
            findings.append(RiskFinding(
                domain="allergy",
                severity=Severity.HIGH,
                drugs=exposed,
                mechanism=(
                    f"Patient is allergic to {raw}. The regimen contains "
                    f"{', '.join(exposed) or canonical} which is the same agent."
                ),
                recommendation=(
                    "Do NOT administer. Choose a non-cross-reacting alternative "
                    "and document the contraindication in the chart."
                ),
                rule_id="ALLERGY_DIRECT_EXPOSURE",
            ))
            continue

        # ── Cross-reactive exposure ──────────────────────────────────────────
        cross_target = _CROSS_REACTIVITY.get(canonical)
        if cross_target and cross_target in exposure_agents:
            exposed = _drugs_for_agent(drugs, cross_target)
            findings.append(RiskFinding(
                domain="allergy",
                severity=Severity.HIGH,
                drugs=exposed,
                mechanism=(
                    f"Patient is allergic to {raw} ({canonical}); the regimen "
                    f"contains {', '.join(exposed) or cross_target} which has "
                    "clinically significant cross-reactivity."
                ),
                recommendation=(
                    "Avoid this agent. Select a non-cross-reacting alternative "
                    "and consider allergy/immunology consultation."
                ),
                rule_id=f"ALLERGY_CROSS_{canonical.upper()}",
            ))

    return findings


def _drugs_for_agent(drugs: list[str], agent: str) -> list[str]:
    """Return the subset of `drugs` that contributed to `agent` exposure."""
    out: list[str] = []
    for d in drugs:
        d_agents = ontology.expand_exposure_to_agents([d])
        if agent in d_agents:
            out.append(d)
    return out

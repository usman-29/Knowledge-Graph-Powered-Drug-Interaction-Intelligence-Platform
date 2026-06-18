"""
Class-level pharmacologic interaction rules.

These are pairwise (or higher-order) rules that depend ONLY on the drug
list and pharmacologic class membership — patient state is unused. They
catch high-risk combinations DDI databases routinely miss because the
risk lives at the class level, not the specific-pair level:

  - Hyperkalemia stacks (K+-sparing × K+-supplement / ACE/ARB / dual-spar)
  - Hypokalemia → digoxin sensitisation
  - QT-prolonger stacking
  - Anticoagulant + antiplatelet bleeding
  - Dual anticoagulation
  - Triple whammy (NSAID + ACE/ARB + diuretic) AKI

Each rule emits a RiskFinding with its own `domain` so arbitration can
group correctly. Pure Python — no LLM.
"""
from __future__ import annotations

from typing import Any

from app.agents import ontology
from app.models.schemas import RiskFinding, Severity


def evaluate(drugs: list[str], patient: dict[str, Any] | None = None) -> list[RiskFinding]:
    """Run every class-effect rule against the drug list. `patient` is
    accepted but unused — kept in the signature so risk_engine can fan out
    all rule modules uniformly."""
    drugs = [d for d in (drugs or []) if d and d.strip()]
    if len(drugs) < 2:
        return []

    findings: list[RiskFinding] = []

    k_sparing = ontology.drugs_in_class(drugs, "k_sparing_diuretic")
    k_supp    = ontology.drugs_in_class(drugs, "k_supplement")
    ace_arb   = ontology.drugs_in_class(drugs, "ace_inhibitor") + ontology.drugs_in_class(drugs, "arb")
    k_wasting = ontology.drugs_in_class(drugs, "loop_diuretic") + ontology.drugs_in_class(drugs, "thiazide_diuretic")
    digoxin   = ontology.drugs_in_class(drugs, "digoxin")
    qt        = ontology.drugs_in_class(drugs, "qt_prolonger")
    nsaid     = ontology.drugs_in_class(drugs, "nsaid")
    anticoag  = ontology.drugs_in_class(drugs, "anticoagulant")
    antiplat  = ontology.drugs_in_class(drugs, "antiplatelet")

    # Rule 1 — K+-sparing diuretic + K+ supplement → hyperkalemia
    for ks in k_sparing:
        for kp in k_supp:
            findings.append(RiskFinding(
                domain="electrolyte",
                severity=Severity.HIGH,
                drugs=[ks, kp],
                mechanism=(
                    "Both elevate serum K+: K+-sparing diuretic blocks renal "
                    "potassium excretion while supplement adds direct K+ load. "
                    "Additive hyperkalemia risk, accentuated in renal impairment."
                ),
                recommendation=(
                    "Avoid combination unless serum K+ is closely monitored "
                    "(target <5.0 mEq/L). Strongly consider withholding the "
                    "K+ supplement; K+-sparing diuretics alone are usually "
                    "sufficient to preserve potassium."
                ),
                rule_id="K_SPARING_PLUS_K_SUPPLEMENT",
            ))

    # Rule 2 — K+-sparing diuretic + ACE/ARB → hyperkalemia
    for ks in k_sparing:
        for ra in ace_arb:
            findings.append(RiskFinding(
                domain="electrolyte",
                severity=Severity.HIGH,
                drugs=[ks, ra],
                mechanism=(
                    "K+-sparing diuretic and ACE/ARB both reduce renal K+ "
                    "excretion via aldosterone-axis suppression. Additive "
                    "hyperkalemia risk."
                ),
                recommendation=(
                    "Check serum K+ and creatinine within 1 week of initiation, "
                    "then every 1–3 months. Hold or reduce dose if K+ >5.5 mEq/L."
                ),
                rule_id="K_SPARING_PLUS_RAAS",
            ))

    # Rule 3 — Two K+-sparing diuretics
    if len(k_sparing) >= 2:
        findings.append(RiskFinding(
            domain="electrolyte",
            severity=Severity.HIGH,
            drugs=k_sparing,
            mechanism="Concurrent K+-sparing diuretics: severe additive hyperkalemia risk.",
            recommendation="Avoid concurrent use; select a single agent.",
            rule_id="DUAL_K_SPARING",
        ))

    # Rule 4 — K+ supplement + ACE/ARB (without K+-sparing)
    if k_supp and ace_arb and not k_sparing:
        for kp in k_supp:
            for ra in ace_arb:
                findings.append(RiskFinding(
                    domain="electrolyte",
                    severity=Severity.MEDIUM,
                    drugs=[kp, ra],
                    mechanism=(
                        "ACE/ARB reduces aldosterone-mediated K+ excretion; "
                        "supplemental K+ may accumulate."
                    ),
                    recommendation=(
                        "Monitor serum K+ periodically. Reassess clinical need "
                        "for K+ supplementation."
                    ),
                    rule_id="K_SUPPLEMENT_PLUS_RAAS",
                ))

    # Rule 5 — K+-wasting diuretic + Digoxin → hypokalemia sensitises to Digoxin toxicity
    for kw in k_wasting:
        for dg in digoxin:
            findings.append(RiskFinding(
                domain="electrolyte",
                severity=Severity.HIGH,
                drugs=[kw, dg],
                mechanism=(
                    f"{kw}-induced hypokalemia and hypomagnesaemia lower the "
                    "threshold for Digoxin-mediated cardiac arrhythmias, even "
                    "at therapeutic Digoxin levels."
                ),
                recommendation=(
                    "Monitor serum K+ and Mg2+; supplement to maintain "
                    "K+ >4.0 mEq/L. Check Digoxin level at steady state and "
                    "after any diuretic dose change."
                ),
                rule_id="K_WASTING_PLUS_DIGOXIN",
            ))

    # Rule 6 — Two or more QT-prolonging agents
    if len(qt) >= 2:
        findings.append(RiskFinding(
            domain="electrolyte",
            severity=Severity.HIGH,
            drugs=qt,
            mechanism=(
                "Additive QTc prolongation. Each QT-prolonging agent compounds "
                "the risk of torsades de pointes."
            ),
            recommendation=(
                "Obtain baseline and follow-up ECG. Avoid combination if "
                "baseline QTc >450 ms (men) / 460 ms (women). Correct K+ and "
                "Mg2+ before initiation."
            ),
            rule_id="DUAL_QT_PROLONGER",
        ))

    # Rule 7 — Anticoagulant + antiplatelet
    for ac in anticoag:
        for ap in antiplat:
            findings.append(RiskFinding(
                domain="ddi",
                severity=Severity.HIGH,
                drugs=[ac, ap],
                mechanism=(
                    "Anticoagulant plus antiplatelet: additive risk of major "
                    "bleeding (GI and intracranial)."
                ),
                recommendation=(
                    "Use only when clearly indicated (e.g. recent coronary "
                    "stent). Add PPI prophylaxis. Use the shortest duration "
                    "consistent with the indication."
                ),
                rule_id="ANTICOAG_PLUS_ANTIPLATELET",
            ))

    # Rule 8 — Two or more anticoagulants
    if len(anticoag) >= 2:
        findings.append(RiskFinding(
            domain="ddi",
            severity=Severity.HIGH,
            drugs=anticoag,
            mechanism="Dual anticoagulation: major bleeding risk.",
            recommendation=(
                "Avoid unless intentionally bridging between agents. Document "
                "indication and end-date."
            ),
            rule_id="DUAL_ANTICOAG",
        ))

    # Rule 9 — Triple whammy: NSAID + ACE/ARB + diuretic → AKI
    diuretic_any = k_wasting + k_sparing
    if nsaid and ace_arb and diuretic_any:
        triple_drugs = list(dict.fromkeys(nsaid + ace_arb + diuretic_any))
        findings.append(RiskFinding(
            domain="class_effect",
            severity=Severity.HIGH,
            drugs=triple_drugs,
            mechanism=(
                "Triple whammy (NSAID + ACE/ARB + diuretic): NSAID-mediated "
                "afferent-arteriole vasoconstriction combines with ACE/ARB "
                "efferent vasodilation and diuretic-induced volume depletion "
                "to drop GFR sharply. Acute kidney injury risk."
            ),
            recommendation=(
                "Avoid NSAID if possible. If unavoidable, use shortest course, "
                "maintain hydration, and check creatinine within 5–7 days."
            ),
            rule_id="TRIPLE_WHAMMY",
        ))

    return findings

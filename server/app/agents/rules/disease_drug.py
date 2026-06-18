"""Disease-state contraindication rules.

These fire on (drug ∈ class, patient has condition) pairs even when the
drug-drug interaction database returns nothing. Designed to fix the
"NSAID + CKD → LOW Risk" failure mode by making the disease side of the
risk explicit and class-based.
"""
from __future__ import annotations

from typing import Any

from app.agents import ontology
from app.agents.rules import _patient as P
from app.models.schemas import RiskFinding, Severity


def evaluate(drugs: list[str], patient: dict[str, Any] | None) -> list[RiskFinding]:
    findings: list[RiskFinding] = []

    nsaids       = ontology.drugs_in_class(drugs, "nsaid")
    ace_arb      = ontology.drugs_in_class(drugs, "ace_inhibitor") + ontology.drugs_in_class(drugs, "arb")
    metformin    = ontology.drugs_in_class(drugs, "metformin")
    triptans     = ontology.drugs_in_class(drugs, "triptan")
    benzos       = ontology.drugs_in_class(drugs, "benzodiazepine")
    ssris        = ontology.drugs_in_class(drugs, "ssri")
    snris        = ontology.drugs_in_class(drugs, "snri")
    maois        = ontology.drugs_in_class(drugs, "maoi")
    anticoag     = ontology.drugs_in_class(drugs, "anticoagulant")
    antiplat     = ontology.drugs_in_class(drugs, "antiplatelet")
    sulfonylurea = ontology.drugs_in_class(drugs, "sulfonylurea")
    digoxin      = ontology.drugs_in_class(drugs, "digoxin")

    age = P.age_of(patient)

    # ── Clinical default: NSAID + (elderly AND CKD AND HF) → HIGH ────────────
    # Explicit trifecta rule. Each pairwise condition already triggers HIGH,
    # but this rule documents the three-condition default clearly and gives
    # the engine an unambiguous record when all three are present together.
    if nsaids and P.is_elderly(patient) and P.has_ckd(patient) and P.has_heart_failure(patient):
        findings.append(RiskFinding(
            domain="disease_drug",
            severity=Severity.HIGH,
            drugs=nsaids,
            mechanism=(
                f"Patient is elderly (age {age}), has CKD, and has heart "
                "failure. NSAIDs in this profile combine afferent renal "
                "vasoconstriction with sodium/water retention and "
                "age-related GI fragility — the absolute risk of AKI, "
                "decompensation, and bleeding is high."
            ),
            recommendation=(
                "Default to HIGH risk for NSAIDs in this patient unless "
                "explicitly overridden by strong, documented clinical "
                "evidence. Prefer acetaminophen, topical diclofenac, or "
                "non-pharmacologic measures."
            ),
            rule_id="NSAID_PLUS_GERIATRIC_CKD_HF",
        ))

    # ── NSAID + CKD → HIGH (afferent vasoconstriction in compromised renal flow)
    if nsaids and P.has_ckd(patient):
        findings.append(RiskFinding(
            domain="disease_drug",
            severity=Severity.HIGH,
            drugs=nsaids,
            mechanism=(
                "NSAID inhibits renal prostaglandin synthesis, dropping GFR. "
                "In CKD this acutely worsens renal function and risks AKI."
            ),
            recommendation=(
                "Avoid NSAIDs. If analgesia is unavoidable, prefer acetaminophen "
                "or short-course topical NSAIDs with renal monitoring."
            ),
            rule_id="NSAID_PLUS_CKD",
        ))

    # ── NSAID + Heart Failure → HIGH (sodium/water retention, decompensation)
    if nsaids and P.has_heart_failure(patient):
        findings.append(RiskFinding(
            domain="disease_drug",
            severity=Severity.HIGH,
            drugs=nsaids,
            mechanism=(
                "NSAIDs cause renal sodium and water retention and antagonise "
                "diuretic / ACE-inhibitor effect, precipitating HF decompensation."
            ),
            recommendation=(
                "Avoid NSAIDs in heart failure. Use acetaminophen or non-NSAID "
                "alternatives; consult cardiology if NSAIDs are essential."
            ),
            rule_id="NSAID_PLUS_HF",
        ))

    # ── NSAID + history of PUD / GI bleed → HIGH
    if nsaids and P.has_pud_or_gib(patient):
        findings.append(RiskFinding(
            domain="disease_drug",
            severity=Severity.HIGH,
            drugs=nsaids,
            mechanism=(
                "NSAIDs disrupt gastric mucosal prostaglandins; in a patient "
                "with prior PUD or GI bleed, recurrence risk is high."
            ),
            recommendation=(
                "Avoid NSAIDs. If essential, co-prescribe a PPI and use the "
                "shortest course at the lowest effective dose."
            ),
            rule_id="NSAID_PLUS_PUD",
        ))

    # ── NSAID + asthma → MODERATE (NSAID-exacerbated respiratory disease)
    if nsaids and P.has_asthma(patient):
        findings.append(RiskFinding(
            domain="disease_drug",
            severity=Severity.MEDIUM,
            drugs=nsaids,
            mechanism=(
                "NSAID/aspirin can trigger bronchospasm in NSAID-exacerbated "
                "respiratory disease (Samter's triad)."
            ),
            recommendation=(
                "Use NSAIDs only if previously tolerated. Document any prior "
                "respiratory reaction; prefer acetaminophen otherwise."
            ),
            rule_id="NSAID_PLUS_ASTHMA",
        ))

    # ── ACE/ARB in pregnancy → HIGH (teratogenic, 2nd/3rd trimester)
    if ace_arb and P.is_pregnant(patient):
        findings.append(RiskFinding(
            domain="disease_drug",
            severity=Severity.HIGH,
            drugs=ace_arb,
            mechanism=(
                "ACE inhibitors and ARBs are fetotoxic — cause oligohydramnios, "
                "renal failure, and skull hypoplasia, especially in 2nd/3rd trimester."
            ),
            recommendation=(
                "Discontinue ACE/ARB. Substitute with a pregnancy-safe agent "
                "(labetalol, methyldopa, nifedipine) and refer to obstetrics."
            ),
            rule_id="ACEI_ARB_PREGNANCY",
        ))

    # ── ACE/ARB + CKD → MODERATE (still indicated but needs monitoring)
    if ace_arb and P.has_ckd(patient):
        findings.append(RiskFinding(
            domain="disease_drug",
            severity=Severity.MEDIUM,
            drugs=ace_arb,
            mechanism=(
                "ACE/ARB can cause an acute creatinine rise and hyperkalemia in "
                "CKD; benefits usually outweigh risks but monitoring is required."
            ),
            recommendation=(
                "Check K+ and creatinine within 1–2 weeks of any dose change. "
                "Hold if creatinine rises >30% from baseline or K+ >5.5."
            ),
            rule_id="ACEI_ARB_PLUS_CKD",
        ))

    # ── Metformin + severe CKD → HIGH (lactic acidosis risk)
    if metformin and P.has_ckd(patient):
        findings.append(RiskFinding(
            domain="disease_drug",
            severity=Severity.HIGH,
            drugs=metformin,
            mechanism=(
                "Metformin is renally cleared; in advanced CKD it accumulates "
                "and raises the risk of lactic acidosis."
            ),
            recommendation=(
                "Verify eGFR. Contraindicated if eGFR <30 mL/min; dose-reduce "
                "or hold for eGFR 30–45. Avoid before/after iodinated contrast."
            ),
            rule_id="METFORMIN_PLUS_CKD",
        ))

    # ── Triptan + coronary artery disease → HIGH
    if triptans and P.has_cad(patient):
        findings.append(RiskFinding(
            domain="disease_drug",
            severity=Severity.HIGH,
            drugs=triptans,
            mechanism=(
                "Triptans are coronary vasoconstrictors; in established CAD they "
                "can precipitate angina or myocardial infarction."
            ),
            recommendation=(
                "Avoid triptans. Use non-vasoconstrictor migraine therapy "
                "(NSAID if no contraindication, gepants, antiemetics)."
            ),
            rule_id="TRIPTAN_PLUS_CAD",
        ))

    # ── Serotonin syndrome risk: SSRI/SNRI + MAOI or + Triptan
    if (ssris or snris) and maois:
        findings.append(RiskFinding(
            domain="disease_drug",
            severity=Severity.HIGH,
            drugs=ssris + snris + maois,
            mechanism=(
                "SSRI/SNRI plus MAOI causes serotonin syndrome: hyperthermia, "
                "rigidity, autonomic instability."
            ),
            recommendation=(
                "Contraindicated. Require a washout (5 weeks for fluoxetine, "
                "2 weeks for other SSRIs/SNRIs) before initiating an MAOI."
            ),
            rule_id="SSRI_SNRI_PLUS_MAOI",
        ))
    if (ssris or snris) and triptans:
        findings.append(RiskFinding(
            domain="disease_drug",
            severity=Severity.MEDIUM,
            drugs=(ssris + snris + triptans),
            mechanism=(
                "Concomitant SSRI/SNRI and triptan elevates risk of serotonin "
                "syndrome, though clinical incidence is low."
            ),
            recommendation=(
                "Counsel the patient on serotonin-syndrome symptoms (agitation, "
                "tremor, hyperreflexia). Avoid combination if alternatives exist."
            ),
            rule_id="SSRI_SNRI_PLUS_TRIPTAN",
        ))

    # ── Anticoagulant or antiplatelet + active GI bleed/PUD history → HIGH
    if (anticoag or antiplat) and P.has_pud_or_gib(patient):
        findings.append(RiskFinding(
            domain="disease_drug",
            severity=Severity.HIGH,
            drugs=anticoag + antiplat,
            mechanism=(
                "Anticoagulant/antiplatelet therapy in a patient with prior "
                "PUD or GI bleed substantially increases rebleeding risk."
            ),
            recommendation=(
                "Re-evaluate indication for anticoagulation/antiplatelet. If "
                "essential, add PPI and consider gastroenterology referral."
            ),
            rule_id="ANTITHROMBOTIC_PLUS_PUD",
        ))

    # ── NSAID + age ≥75 → HIGH (geriatric NSAID risk dominates Beers MEDIUM)
    if nsaids and age is not None and age >= 75:
        findings.append(RiskFinding(
            domain="disease_drug",
            severity=Severity.HIGH,
            drugs=nsaids,
            mechanism=(
                f"Patient is {age}. NSAIDs in adults ≥75 carry a substantially "
                "elevated risk of AKI, GI bleeding, and HF decompensation; the "
                "absolute event rate dominates the Beers Criteria's MODERATE "
                "baseline at this age threshold."
            ),
            recommendation=(
                "Avoid NSAIDs as first-line. Prefer acetaminophen, topical "
                "diclofenac (limited systemic exposure), or non-pharmacologic "
                "options. If unavoidable, use the shortest course possible "
                "with a PPI and renal-function monitoring."
            ),
            rule_id="NSAID_PLUS_AGE_GE_75",
        ))

    # ── NSAID + concomitant Digoxin → HIGH
    # NSAIDs reduce renal clearance of digoxin and (via sodium retention)
    # destabilise the cardiac substrate digoxin already sensitises. Not a
    # classic DDI row in most databases; surfaces here as class+drug.
    if nsaids and digoxin:
        findings.append(RiskFinding(
            domain="disease_drug",
            severity=Severity.HIGH,
            drugs=nsaids + digoxin,
            mechanism=(
                "NSAIDs reduce renal clearance of digoxin and cause sodium/"
                "fluid retention, raising serum digoxin and the risk of "
                "arrhythmia in a patient already on a narrow-TI agent."
            ),
            recommendation=(
                "Avoid NSAIDs in patients on digoxin. If essential, recheck "
                "digoxin level, K+, Mg2+, and creatinine within 3–5 days of "
                "starting the NSAID, then weekly."
            ),
            rule_id="NSAID_PLUS_DIGOXIN",
        ))

    # ── Sulfonylurea + CKD → MODERATE (prolonged hypoglycaemia)
    if sulfonylurea and P.has_ckd(patient):
        findings.append(RiskFinding(
            domain="disease_drug",
            severity=Severity.MEDIUM,
            drugs=sulfonylurea,
            mechanism=(
                "Sulfonylureas accumulate in CKD, producing prolonged and "
                "severe hypoglycaemia (glyburide especially)."
            ),
            recommendation=(
                "Prefer glipizide if a sulfonylurea is required. Avoid "
                "glyburide in eGFR <60. Consider DPP-4 inhibitor or insulin."
            ),
            rule_id="SULFONYLUREA_PLUS_CKD",
        ))

    return findings

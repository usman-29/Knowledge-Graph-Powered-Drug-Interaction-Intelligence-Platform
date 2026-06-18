"""
Regression tests for the deterministic risk engine.

Every test exercises one of the failure modes the architecture rework was
meant to fix:

  - NSAIDs in CKD / HF / PUD / asthma must escalate.
  - Digoxin in CKD must escalate (toxicity risk).
  - Beers Criteria must fire on age ≥65 medications.
  - Allergy + cross-reactivity must dominate neutral DDI findings.
  - Iodinated-contrast synonyms ("contrast dye", "iodine contrast", …) must
    map to the same canonical agent.
  - Unmappable allergy / RxCUI NOT_FOUND must ESCALATE caution, never reduce
    risk.
  - Disease-drug contraindications must override the LLM's draft severity.
  - One severe contraindication must dominate many neutral interactions.

These tests are pure-Python — they call the risk engine functions
directly with crafted state. No LLM, no Neo4j (SNOMED enrichment in
ontology.normalise_allergy fails silently when the graph isn't reachable).
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from app.agents import arbitration
from app.agents.rules import (
    allergy,
    beers_criteria,
    blackbox_amplifier,
    disease_drug,
    organ_dysfunction,
)
from app.models.schemas import Severity


# ── Helpers ────────────────────────────────────────────────────────────────────

def _patient(**kwargs) -> dict:
    """Build a minimal patient dict suitable for the rule modules."""
    return {
        "age": kwargs.get("age", 50),
        "sex": kwargs.get("sex", "F"),
        "conditions": kwargs.get("conditions", []),
        "allergies":  kwargs.get("allergies", []),
        "medications": kwargs.get("medications", []),
    }


def _severities(findings) -> list[str]:
    return [f.severity.value for f in findings]


def _rule_ids(findings) -> set[str]:
    return {f.rule_id for f in findings}


# ── NSAID + disease state ─────────────────────────────────────────────────────

class TestNSAIDDiseaseStates:
    def test_nsaid_ckd_is_high(self):
        p = _patient(age=68, conditions=["Chronic kidney disease stage 3"])
        findings = disease_drug.evaluate(["Ketorolac"], p)
        assert "NSAID_PLUS_CKD" in _rule_ids(findings)
        nsaid_ckd = [f for f in findings if f.rule_id == "NSAID_PLUS_CKD"][0]
        assert nsaid_ckd.severity == Severity.HIGH

    def test_nsaid_hf_is_high(self):
        p = _patient(age=72, conditions=["Congestive heart failure"])
        findings = disease_drug.evaluate(["Ibuprofen"], p)
        assert "NSAID_PLUS_HF" in _rule_ids(findings)
        assert all(f.severity == Severity.HIGH for f in findings if f.rule_id == "NSAID_PLUS_HF")

    def test_nsaid_pud_is_high(self):
        p = _patient(conditions=["History of GI bleed"])
        findings = disease_drug.evaluate(["Naproxen"], p)
        assert "NSAID_PLUS_PUD" in _rule_ids(findings)

    def test_nsaid_asthma_is_moderate(self):
        p = _patient(conditions=["Asthma"])
        findings = disease_drug.evaluate(["Ibuprofen"], p)
        nsaid_asthma = [f for f in findings if f.rule_id == "NSAID_PLUS_ASTHMA"]
        assert nsaid_asthma and nsaid_asthma[0].severity == Severity.MEDIUM

    def test_acetaminophen_in_ckd_does_not_trigger_nsaid_rule(self):
        p = _patient(conditions=["CKD stage 4"])
        findings = disease_drug.evaluate(["Acetaminophen"], p)
        assert "NSAID_PLUS_CKD" not in _rule_ids(findings)


# ── Digoxin + organ dysfunction ──────────────────────────────────────────────

class TestDigoxinToxicity:
    def test_digoxin_ckd_is_high(self):
        p = _patient(age=78, conditions=["Chronic kidney disease"])
        findings = organ_dysfunction.evaluate(["Digoxin"], p)
        assert "DIGOXIN_CKD_TOXICITY" in _rule_ids(findings)
        dig = [f for f in findings if f.rule_id == "DIGOXIN_CKD_TOXICITY"][0]
        assert dig.severity == Severity.HIGH

    def test_digoxin_normal_renal_not_high_organ_rule(self):
        p = _patient(conditions=["Hypertension"])
        findings = organ_dysfunction.evaluate(["Digoxin"], p)
        assert "DIGOXIN_CKD_TOXICITY" not in _rule_ids(findings)


# ── Hyperkalemia combinations (class_effects rule module) ───────────────────

class TestHyperkalemiaCombinations:
    def test_k_sparing_plus_ace_is_high(self):
        from app.agents.rules import class_effects
        findings = class_effects.evaluate(["Spironolactone", "Lisinopril"])
        assert any(
            f.rule_id == "K_SPARING_PLUS_RAAS" and f.severity == Severity.HIGH
            for f in findings
        )

    def test_triple_whammy_is_high(self):
        from app.agents.rules import class_effects
        findings = class_effects.evaluate(["Ibuprofen", "Lisinopril", "Furosemide"])
        assert any(
            f.rule_id == "TRIPLE_WHAMMY" and f.severity == Severity.HIGH
            for f in findings
        )


# ── Beers Criteria geriatric ─────────────────────────────────────────────────

class TestBeersCriteria:
    def test_benzodiazepine_in_elderly_is_high(self):
        p = _patient(age=82)
        findings = beers_criteria.evaluate(["Lorazepam"], p)
        rule_ids = _rule_ids(findings)
        assert "BEERS_BENZODIAZEPINE" in rule_ids
        benzo = [f for f in findings if f.rule_id == "BEERS_BENZODIAZEPINE"][0]
        assert benzo.severity == Severity.HIGH

    def test_tca_in_elderly_is_high(self):
        p = _patient(age=70)
        findings = beers_criteria.evaluate(["Amitriptyline"], p)
        assert "BEERS_TCA" in _rule_ids(findings)

    def test_glyburide_in_elderly_is_high(self):
        p = _patient(age=75)
        findings = beers_criteria.evaluate(["Glyburide"], p)
        sulf = [f for f in findings if f.rule_id == "BEERS_SULFONYLUREA"]
        assert sulf and sulf[0].severity == Severity.HIGH

    def test_beers_skipped_for_under_65(self):
        p = _patient(age=40)
        findings = beers_criteria.evaluate(["Lorazepam", "Diphenhydramine"], p)
        assert findings == []


# ── Allergy / cross-reactivity / contrast synonyms ───────────────────────────

class TestAllergyAndContrast:
    def test_aspirin_allergy_with_aspirin_exposure_is_high(self):
        p = _patient(allergies=["Aspirin"])
        findings = allergy.evaluate(["Aspirin"], p)
        assert any(
            f.severity == Severity.HIGH and f.rule_id == "ALLERGY_DIRECT_EXPOSURE"
            for f in findings
        )

    def test_aspirin_allergy_with_nsaid_class_cross_reactivity_is_high(self):
        # Aspirin allergy → ketorolac (NSAID class) should be flagged cross-reactive
        p = _patient(allergies=["Aspirin"])
        findings = allergy.evaluate(["Ketorolac"], p)
        cross = [f for f in findings if f.rule_id.startswith("ALLERGY_CROSS_")]
        assert cross and cross[0].severity == Severity.HIGH

    @pytest.mark.parametrize("allergy_text", [
        "Iodinated contrast",
        "Contrast dye",
        "Iodine contrast",
        "Contrast media",
        "Iodinated dye",
        "Radiocontrast",
    ])
    def test_iodinated_contrast_synonyms_collapse(self, allergy_text):
        p = _patient(allergies=[allergy_text])
        findings = allergy.evaluate(["Iohexol"], p)
        assert any(
            f.rule_id == "ALLERGY_DIRECT_EXPOSURE" and f.severity == Severity.HIGH
            for f in findings
        )

    def test_unmapped_allergy_escalates_uncertainty_not_silence(self):
        # SNOMED enrichment is patched to None so we exercise the pure-Python miss path.
        with patch("app.agents.ontology._snomed_lookup", return_value=None):
            p = _patient(allergies=["XYZ-99 monoclonal antibody"])
            findings = allergy.evaluate(["Apixaban"], p)
        unmapped = [f for f in findings if f.rule_id == "ALLERGY_UNMAPPED"]
        assert unmapped
        assert unmapped[0].uncertain is True
        # Caution must escalate to at least MODERATE — never LOW.
        assert unmapped[0].severity == Severity.MEDIUM


# ── Black-box amplifier ──────────────────────────────────────────────────────

class TestBlackboxAmplifier:
    def _evidence(self, result: str) -> list[dict]:
        return [{
            "tool": "get_fda_blackbox_warning",
            "args": {"rxcui": "1191"},
            "result": result,
        }]

    def test_bbw_in_vulnerable_patient_escalates_to_high(self):
        ev = self._evidence("FDA boxed warning: Risk of agranulocytosis...")
        p = _patient(age=80)
        findings = blackbox_amplifier.evaluate(["Clozapine"], p, ev)
        assert any(
            f.rule_id == "BBW_VULNERABLE_PATIENT" and f.severity == Severity.HIGH
            for f in findings
        )

    def test_bbw_in_healthy_adult_is_moderate(self):
        ev = self._evidence("FDA boxed warning: Risk of agranulocytosis...")
        p = _patient(age=35)
        findings = blackbox_amplifier.evaluate(["Clozapine"], p, ev)
        assert any(
            f.rule_id == "BBW_PRESENT" and f.severity == Severity.MEDIUM
            for f in findings
        )

    def test_no_bbw_on_file_produces_no_finding(self):
        ev = self._evidence("No FDA boxed warning on file for this medication.")
        findings = blackbox_amplifier.evaluate(["Acetaminophen"], _patient(), ev)
        assert findings == []


# ── Arbitration — max-severity, uncertainty, contradiction ───────────────────

class TestArbitration:
    def _f(self, severity, rule_id="R", domain="ddi", uncertain=False):
        from app.models.schemas import RiskFinding
        return RiskFinding(
            domain=domain,
            severity=severity,
            drugs=["X"],
            mechanism="m",
            recommendation="r",
            rule_id=rule_id,
            uncertain=uncertain,
        )

    def test_one_high_dominates_many_lows(self):
        findings = [self._f(Severity.LOW, rule_id=f"LOW{i}") for i in range(20)]
        findings.append(self._f(Severity.HIGH, rule_id="ONE_HIGH"))
        ra = arbitration.arbitrate(findings)
        assert ra.final_severity == Severity.HIGH

    def test_critical_dominates_high(self):
        findings = [
            self._f(Severity.HIGH, rule_id="A"),
            self._f(Severity.CRITICAL, rule_id="B"),
        ]
        ra = arbitration.arbitrate(findings)
        assert ra.final_severity == Severity.CRITICAL

    def test_no_findings_no_contradictions_is_low(self):
        # Pure clinical signal: nothing fired, no narrative concerns → LOW.
        # The LLM's draft severity is no longer an arbitration input.
        ra = arbitration.arbitrate([])
        assert ra.final_severity == Severity.LOW
        assert ra.insufficient_data is False

    def test_narrative_blackbox_escalates_from_low(self):
        ra = arbitration.arbitrate(
            [],
            narrative_text="There is a black box warning to be aware of.",
        )
        assert ra.final_severity == Severity.MEDIUM
        assert ra.contradictions

    def test_narrative_renal_impairment_escalates_from_low(self):
        ra = arbitration.arbitrate(
            [],
            narrative_text="Caution in patients with renal impairment.",
        )
        assert ra.final_severity == Severity.MEDIUM

    def test_contradiction_does_not_downgrade_high(self):
        findings = [self._f(Severity.HIGH, rule_id="X")]
        ra = arbitration.arbitrate(findings, narrative_text="renal impairment")
        assert ra.final_severity == Severity.HIGH


# ── Insufficient-clinical-data invariant — HIGH not LOW or MODERATE ────────

class TestInsufficientClinicalDataInvariant:
    """Requirement #5: when clinical reasoning fails, return HIGH RISK –
    INSUFFICIENT DATA. Never LOW, never MODERATE-by-default.

    This is the ONE path that returns HIGH without a matching clinical
    finding. It fires only when the medical_agent could not produce any
    clinical signal (e.g. crashed before extracting drugs)."""

    def test_insufficient_data_returns_high(self):
        ra = arbitration.arbitrate([], insufficient_clinical_data=True)
        assert ra.final_severity == Severity.HIGH
        assert ra.insufficient_data is True

    def test_findings_still_evaluated_under_insufficient_data(self):
        from app.models.schemas import RiskFinding
        # Even when the engine flags insufficient_data, the findings list
        # is still preserved (for audit), but severity is HIGH by design.
        findings = [RiskFinding(
            domain="disease_drug", severity=Severity.MEDIUM, drugs=["X"],
            mechanism="m", recommendation="r", rule_id="R",
        )]
        ra = arbitration.arbitrate(findings, insufficient_clinical_data=True)
        assert ra.final_severity == Severity.HIGH
        assert ra.insufficient_data is True
        assert len(ra.findings) == 1

    def test_clean_reasoning_no_insufficient_flag(self):
        ra = arbitration.arbitrate([])
        assert ra.insufficient_data is False
        assert ra.final_severity == Severity.LOW


# ── Strict layer separation: tool failures do NOT influence severity ─────

class TestToolFailureDoesNotInfluenceRisk:
    """Requirement #3, #6: parsing failures / tool errors must NOT change the
    risk label. Clinical rules run on drug names + patient state, both of
    which survive tool outages."""

    def test_rules_still_fire_when_tools_failed(self):
        # Tools (resolve_rxcui, FDA, etc.) failed — no evidence — but the
        # drug name + patient condition is enough for disease_drug rules.
        p = _patient(age=70, conditions=["Chronic kidney disease"])
        findings = disease_drug.evaluate(["Ketorolac"], p)
        assert any(
            f.rule_id == "NSAID_PLUS_CKD" and f.severity == Severity.HIGH
            for f in findings
        )

    def test_arbitrate_does_not_take_reasoning_failed_param(self):
        """The old `reasoning_failed=` floor is gone. arbitrate() now only
        accepts findings, narrative_text, and insufficient_clinical_data."""
        import inspect
        params = set(inspect.signature(arbitration.arbitrate).parameters)
        assert "reasoning_failed" not in params
        assert "insufficient_clinical_data" in params

    def test_merge_uncertainty_from_evidence_removed(self):
        """Tool-derived 'uncertainty findings' (e.g. NOT_FOUND RxCUI) no
        longer get auto-injected as MEDIUM findings — that conflated tool
        failure with clinical uncertainty."""
        assert not hasattr(arbitration, "merge_uncertainty_from_evidence")


# ── High-risk-patient NSAID escalation ──────────────────────────────────────

class TestHighRiskPatientNSAIDInvariant:
    """Requirement: NSAIDs in CKD / HF / age ≥75 / digoxin user MUST be HIGH."""

    def test_ketorolac_in_age_75_is_high(self):
        p = _patient(age=75)
        findings = disease_drug.evaluate(["Ketorolac"], p)
        ids = _rule_ids(findings)
        assert "NSAID_PLUS_AGE_GE_75" in ids
        rule = [f for f in findings if f.rule_id == "NSAID_PLUS_AGE_GE_75"][0]
        assert rule.severity == Severity.HIGH

    def test_ketorolac_in_age_80_is_high(self):
        p = _patient(age=80)
        findings = disease_drug.evaluate(["Ketorolac"], p)
        assert any(
            f.rule_id == "NSAID_PLUS_AGE_GE_75" and f.severity == Severity.HIGH
            for f in findings
        )

    def test_ketorolac_in_age_70_not_age_rule(self):
        # Age 70 is still in Beers (≥65) but below the new HIGH threshold.
        p = _patient(age=70)
        findings = disease_drug.evaluate(["Ketorolac"], p)
        assert "NSAID_PLUS_AGE_GE_75" not in _rule_ids(findings)

    def test_ketorolac_with_digoxin_is_high(self):
        p = _patient(age=60)
        findings = disease_drug.evaluate(["Ketorolac", "Digoxin"], p)
        ids = _rule_ids(findings)
        assert "NSAID_PLUS_DIGOXIN" in ids
        rule = [f for f in findings if f.rule_id == "NSAID_PLUS_DIGOXIN"][0]
        assert rule.severity == Severity.HIGH

    def test_ibuprofen_with_digoxin_is_high(self):
        p = _patient(age=50)
        findings = disease_drug.evaluate(["Ibuprofen", "Digoxin"], p)
        assert any(
            f.rule_id == "NSAID_PLUS_DIGOXIN" and f.severity == Severity.HIGH
            for f in findings
        )

    def test_acetaminophen_with_digoxin_does_not_fire_nsaid_digoxin(self):
        p = _patient(age=50)
        findings = disease_drug.evaluate(["Acetaminophen", "Digoxin"], p)
        assert "NSAID_PLUS_DIGOXIN" not in _rule_ids(findings)


# ── Contradiction checker — clinical tokens only ────────────────────────────

class TestClinicalContradictionEscalation:
    """Clinical-narrative contradictions (renal impairment, BBW, …) still
    escalate LOW → MEDIUM. System-error tokens no longer participate —
    they're not in the output and don't influence risk."""

    def test_renal_impairment_token_escalates_from_low(self):
        ra = arbitration.arbitrate(
            [],
            narrative_text="Caution in patients with renal impairment.",
        )
        assert ra.final_severity == Severity.MEDIUM
        assert ra.insufficient_data is False

    def test_blackbox_token_escalates_from_low(self):
        ra = arbitration.arbitrate(
            [],
            narrative_text="There is a black-box warning to be aware of.",
        )
        assert ra.final_severity == Severity.MEDIUM

    def test_system_error_tokens_do_NOT_escalate(self):
        """The previous architecture pinned MODERATE when 'could not be
        completed reliably' appeared. That conflated system failure with
        clinical uncertainty. Now: system tokens are no longer in the
        output, and even if they slip in, arbitration ignores them."""
        ra = arbitration.arbitrate(
            [],
            narrative_text="This safety check could not be completed reliably.",
        )
        # No clinical findings, no clinical contradictions → LOW.
        # The fail-safe for genuine reasoning failure is the explicit
        # insufficient_clinical_data flag, not narrative scanning.
        assert ra.final_severity == Severity.LOW


# ── Trifecta clinical default — NSAID + elderly + CKD + HF ──────────────────

class TestTrifectaClinicalDefault:
    """Requirement #7: For elderly + CKD + HF: NSAIDs default to HIGH."""

    def test_trifecta_fires_with_explicit_rule_id(self):
        p = _patient(age=78, conditions=["CKD stage 3", "Heart failure"])
        findings = disease_drug.evaluate(["Ibuprofen"], p)
        ids = _rule_ids(findings)
        assert "NSAID_PLUS_GERIATRIC_CKD_HF" in ids
        rule = [f for f in findings if f.rule_id == "NSAID_PLUS_GERIATRIC_CKD_HF"][0]
        assert rule.severity == Severity.HIGH

    def test_trifecta_fires_for_ketorolac(self):
        p = _patient(age=68, conditions=["Chronic kidney disease", "Congestive heart failure"])
        findings = disease_drug.evaluate(["Ketorolac"], p)
        assert any(
            f.rule_id == "NSAID_PLUS_GERIATRIC_CKD_HF" and f.severity == Severity.HIGH
            for f in findings
        )

    def test_trifecta_does_not_fire_without_all_three(self):
        # Missing HF
        p = _patient(age=78, conditions=["Chronic kidney disease"])
        findings = disease_drug.evaluate(["Ibuprofen"], p)
        assert "NSAID_PLUS_GERIATRIC_CKD_HF" not in _rule_ids(findings)
        # Missing CKD
        p2 = _patient(age=78, conditions=["Heart failure"])
        findings2 = disease_drug.evaluate(["Ibuprofen"], p2)
        assert "NSAID_PLUS_GERIATRIC_CKD_HF" not in _rule_ids(findings2)
        # Missing elderly (age < 65)
        p3 = _patient(age=50, conditions=["CKD", "Heart failure"])
        findings3 = disease_drug.evaluate(["Ibuprofen"], p3)
        assert "NSAID_PLUS_GERIATRIC_CKD_HF" not in _rule_ids(findings3)


# ── Render: HIGH RISK – INSUFFICIENT DATA label ─────────────────────────────

class TestInsufficientDataRendering:
    def test_render_label_includes_insufficient_data_suffix(self):
        from app.agents.risk_engine import _severity_label
        from app.models.schemas import RiskAssessment

        ra = RiskAssessment(
            final_severity=Severity.HIGH,
            findings=[],
            contradictions=[],
            insufficient_data=True,
        )
        label = _severity_label(ra)
        assert "Insufficient Data" in label
        assert "High Risk" in label

    def test_render_label_omits_suffix_for_clinical_high(self):
        from app.agents.risk_engine import _severity_label
        from app.models.schemas import RiskAssessment

        ra = RiskAssessment(
            final_severity=Severity.HIGH,
            findings=[],
            insufficient_data=False,
        )
        label = _severity_label(ra)
        assert "Insufficient Data" not in label
        assert "High Risk" in label


# ── Output sanitisation — no system errors in user-facing prose ────────────

class TestNoSystemErrorsInUserOutput:
    def test_safe_response_strips_internal_failures(self):
        from app.agents.graph import _sanitize_block_reason

        # Internal failure reasons → generic refusal.
        assert "crashed" not in _sanitize_block_reason(
            "Input guardrail crashed (KeyError); failing closed."
        )
        assert "Router unavailable" not in _sanitize_block_reason(
            "Router unavailable (timeout); failing closed."
        ).lower()

    def test_safe_response_preserves_clean_policy_reasons(self):
        from app.agents.graph import _sanitize_block_reason

        # Clean policy verdicts pass through.
        assert _sanitize_block_reason("Non-clinical query.") == "Non-clinical query."
        assert _sanitize_block_reason("Off-topic.") == "Off-topic."

    def test_safe_response_handles_none(self):
        from app.agents.graph import _sanitize_block_reason
        out = _sanitize_block_reason(None)
        assert out  # non-empty generic refusal
        assert "exception" not in out.lower()


# ── End-to-end: disease contraindication dominates neutral DDIs ─────────────

class TestRiskEngineEndToEnd:
    """Compose multiple rule families and confirm the dominant risk wins —
    a single NSAID+CKD finding must keep the final label HIGH no matter how
    many neutral DDIs come from the pairwise database."""

    def test_nsaid_ckd_dominates_neutral_ddis(self):
        # Patient: 70F, CKD. Regimen: Ketorolac (NSAID, no DDIs).
        from app.agents.rules import class_effects

        p = _patient(age=70, conditions=["Chronic kidney disease"])
        drugs = ["Ketorolac"]
        findings = []
        findings.extend(class_effects.evaluate(drugs, p))
        findings.extend(disease_drug.evaluate(drugs, p))
        findings.extend(organ_dysfunction.evaluate(drugs, p))
        findings.extend(beers_criteria.evaluate(drugs, p))

        ra = arbitration.arbitrate(findings)
        assert ra.final_severity == Severity.HIGH
        assert any(f.rule_id == "NSAID_PLUS_CKD" for f in ra.findings)

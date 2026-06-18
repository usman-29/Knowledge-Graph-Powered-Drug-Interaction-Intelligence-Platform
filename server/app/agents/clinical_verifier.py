"""
Clinical verifier — three-pass safety reasoning.

Pass 0 (rules): Findings produced by the upstream risk_engine node
  (deterministic, class-level). Re-read from state instead of recomputed.
  Drives severity for any claim whose drugs match a rule.

Pass 1 (per-claim): Scores each safety_warning against the retrieved evidence
  on a -2 to +2 scale and validates pharmacological direction. Severity is
  pinned to the rules-engine output when a rule fires; otherwise the LLM
  proposes RED/ORANGE/GREEN.

Pass 2 (holistic): LLM reasoning over drugs not covered by rules — catches
  HIGH/CRITICAL pairs the drug-interaction database missed or cleared.

Both LLM passes call HuggingFace Inference Providers (OpenAI-compatible).
Fail-open: if either pass errors, the report passes through unchanged.
"""
from __future__ import annotations

import logging
import re
import time

import requests

from app.agents import arbitration
from app.config.settings import settings
from app.models.schemas import AgentTrace, Severity
from app.models.state import AgentState

logger = logging.getLogger(__name__)
AGENT_NAME = "clinical_verifier"

_MAX_NEW_TOKENS    = 2048
_MAX_ARTICLE_CHARS = 4000
_MAX_CLAIMS        = 8
_REQUEST_TIMEOUT_S = 90


# ── System prompts ─────────────────────────────────────────────────────────────

_CLAIM_SYSTEM_PROMPT = (
    "You are a medical verifier. Fact-check a single clinical safety claim "
    "in three stages:\n\n"
    "STAGE 1 — Evidence match\n"
    "Score how strongly the article supports or refutes the claim:\n"
    "   -2  Strong contradiction  — article clearly refutes the claim.\n"
    "   -1  Partial contradiction — article gives mixed or indirect evidence against it.\n"
    "    0  Neutral / unrelated   — article does not address the claim.\n"
    "   +1  Partial agreement     — article offers some indirect or tentative support.\n"
    "   +2  Strong agreement      — article explicitly and strongly supports the claim.\n\n"
    "STAGE 2 — Pharmacological direction check\n"
    "Even when the article text matches the claim, apply clinical pharmacology to "
    "detect direction errors:\n"
    "  • A claim says Drug A's serum concentration increases with Drug B, but the "
    "known PK mechanism acts on Drug B (victim/perpetrator swap).\n"
    "  • A claim attributes a metabolic pathway (CYP, P-gp, renal clearance) to "
    "the wrong drug in the pair.\n"
    "  • A claim reverses the pharmacodynamic synergy direction.\n"
    "If the article agrees but the direction is pharmacologically implausible, "
    "downgrade the score by 2 and explain the correct direction.\n\n"
    "STAGE 3 — Severity classification\n"
    "Assign a clinical severity for this interaction:\n"
    "  RED    — life-threatening or contraindicated "
    "(arrhythmia, hyperkalemia, serotonin syndrome, QTc >500 ms, etc.)\n"
    "  ORANGE — clinically significant, requires monitoring or dose adjustment.\n"
    "  GREEN  — minor, informational only.\n\n"
    "Reason step-by-step through all three stages, then end with EXACTLY:\n"
    "<score>N</score>\n"
    "<severity>LEVEL</severity>\n"
    "where N ∈ {-2,-1,0,1,2} and LEVEL ∈ {RED,ORANGE,GREEN}. "
    "Nothing after the last tag."
)

_HOLISTIC_SYSTEM_PROMPT = (
    "You are a senior clinical pharmacist performing a final safety screen on a "
    "discharge drug regimen. A deterministic rules engine has ALREADY flagged "
    "the high-certainty class-level risks (listed under 'RULES ENGINE HITS' in "
    "the context). Your job is to find what the rules engine and the DDI "
    "database both missed.\n\n"
    "TASK 1 — Physiological Rule Validation (residual)\n"
    "Identify physiological-rule violations NOT already in RULES ENGINE HITS. "
    "Focus on:\n"
    "  • Electrolytes beyond the K⁺ axis: hyponatraemia, hypomagnesaemia, "
    "hypocalcaemia.\n"
    "  • Cardiac: bradycardia synergism, AV-node-blocker stacking.\n"
    "  • Renal: dual nephrotoxic agents, competition for tubular secretion.\n"
    "  • Narrow-TI vigilance: Warfarin, Lithium, Phenytoin co-prescribing.\n\n"
    "TASK 2 — Negative-Space Detection\n"
    "Review the drug list and the warnings already generated. Identify RED or ORANGE "
    "drug pairs that should have been flagged but were NOT — either because the pair "
    "returned 'no recorded interaction' from the database, or was never queried. "
    "Do NOT restate any pair already in RULES ENGINE HITS. Only flag pairs you are "
    "clinically certain about. Do not speculate.\n\n"
    "Output EXACTLY this format (pipe-separated, one entry per line):\n"
    "<physiological_issues>\n"
    "SEVERITY | Drug A + Drug B | Mechanism | Clinical recommendation\n"
    "[or NONE]\n"
    "</physiological_issues>\n"
    "<missing_interactions>\n"
    "SEVERITY | Drug A + Drug B | Clinical risk | Why it was likely missed\n"
    "[or NONE]\n"
    "</missing_interactions>\n"
    "Severity: RED (life-threatening), ORANGE (clinically significant). "
    "Omit GREEN entries."
)


# ── Lookup tables ──────────────────────────────────────────────────────────────

_VERDICT_LABEL = {
    -2: "⛔ Strong contradiction",
    -1: "⚠️ Partial contradiction",
    0:  "ℹ️ Neutral / unrelated",
    1:  "✓ Partial agreement",
    2:  "✅ Strong agreement",
}

_SEVERITY_BADGE = {"RED": "🔴", "ORANGE": "🟠", "GREEN": "🟢"}

# The per-claim verifier prompts the LLM to emit RED / ORANGE / GREEN so its
# internal scoring vocabulary diverges from the global Severity enum. This
# adapter maps the global enum back to the verifier-local label when pinning
# Pass-1 severity to a risk-engine finding.
_NEW_TO_LEGACY_SEVERITY = {
    "CRITICAL": "RED",
    "HIGH":     "RED",
    "MEDIUM":   "ORANGE",
    "LOW":      "GREEN",
}


def _legacy_severity(new_value: str | None) -> str | None:
    if not new_value:
        return None
    return _NEW_TO_LEGACY_SEVERITY.get(new_value.upper(), new_value)

# Evidence tool priority: pairwise checks first, bulk lookups last.
# Ensures the 4 000-char article budget goes to claims-grounding evidence,
# not to the check_local_interactions result (potentially thousands of chars).
_EVIDENCE_PRIORITY = {
    "check_interaction_pair":   0,
    "get_fda_blackbox_warning": 1,
    "resolve_rxcui":            2,
    "check_local_interactions": 3,
}


# ── Regex parsers ──────────────────────────────────────────────────────────────

_SCORE_RE    = re.compile(r"<score>\s*(-?\d+)\s*</score>",          re.IGNORECASE)
_THINK_RE    = re.compile(r"<think>(.*?)</think>",                   re.IGNORECASE | re.DOTALL)
_SEVERITY_RE = re.compile(r"<severity>\s*(RED|ORANGE|GREEN)\s*</severity>", re.IGNORECASE)
_PHYSIO_RE   = re.compile(r"<physiological_issues>(.*?)</physiological_issues>", re.IGNORECASE | re.DOTALL)
_MISSING_RE  = re.compile(r"<missing_interactions>(.*?)</missing_interactions>",  re.IGNORECASE | re.DOTALL)


# ── Shared HTTP helper ─────────────────────────────────────────────────────────

def _hf_chat(system: str, user: str, max_tokens: int = _MAX_NEW_TOKENS) -> str | None:
    """Single OpenAI-compatible chat call to the HuggingFace Inference Providers router.
    Returns raw assistant content, or None on any error."""
    payload = {
        "model": settings.VERIFIER_MODEL_ID,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user",   "content": user},
        ],
        "max_tokens": max_tokens,
        "temperature": 0,
        "stream": False,
    }
    headers = {
        "Authorization": f"Bearer {settings.HUGGINGFACE_TOKEN}",
        "Content-Type": "application/json",
    }
    try:
        response = requests.post(
            settings.VERIFIER_API_URL,
            headers=headers,
            json=payload,
            timeout=_REQUEST_TIMEOUT_S,
        )
    except requests.RequestException as exc:
        logger.warning("[%s] Network error: %s", AGENT_NAME, exc)
        return None

    if response.status_code != 200:
        logger.warning("[%s] API %d: %s", AGENT_NAME, response.status_code, (response.text or "")[:200])
        return None

    try:
        return response.json()["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError) as exc:
        logger.warning("[%s] Bad response shape: %s", AGENT_NAME, exc)
        return None


# ── Pass 1: per-claim verification ────────────────────────────────────────────

def _verify_claim(article: str, claim: str) -> dict:
    """Score one claim against the article.
    Returns {score, severity, reasoning, error}."""
    raw = _hf_chat(_CLAIM_SYSTEM_PROMPT, f"Article:\n{article}\n\nClaim:\n{claim}")
    if raw is None:
        return {"score": None, "severity": None, "reasoning": "API unavailable.", "error": "api"}

    score_match    = _SCORE_RE.search(raw)
    severity_match = _SEVERITY_RE.search(raw)
    think_match    = _THINK_RE.search(raw)

    score: int | None = int(score_match.group(1)) if score_match else None
    if score is not None and score not in _VERDICT_LABEL:
        score = None

    severity: str | None = severity_match.group(1).upper() if severity_match else None
    reasoning = think_match.group(1).strip() if think_match else raw[:500]

    return {"score": score, "severity": severity, "reasoning": reasoning, "error": None}


# ── Pass 2: holistic clinical reasoning ───────────────────────────────────────

def _holistic_clinical_check(
    drugs: list[str],
    evidence: list[dict],
    warnings: list[str],
    rule_findings: list[dict],
) -> dict:
    """Physiological rule validation + negative-space detection over the full regimen.
    Rule-engine hits are passed as context so the LLM doesn't restate them.
    `rule_findings` are RiskFinding dicts pulled from state["risk_assessment"].
    Returns {physiological_issues, missing_interactions, error}."""
    context = _build_holistic_context(drugs, evidence, warnings, rule_findings)
    raw = _hf_chat(_HOLISTIC_SYSTEM_PROMPT, context, max_tokens=2048)
    if raw is None:
        return {"physiological_issues": [], "missing_interactions": [], "error": "api"}

    physio_match  = _PHYSIO_RE.search(raw)
    missing_match = _MISSING_RE.search(raw)

    return {
        "physiological_issues": _parse_alert_lines(physio_match.group(1)  if physio_match  else ""),
        "missing_interactions":  _parse_alert_lines(missing_match.group(1) if missing_match else ""),
        "error": None,
    }


def _build_holistic_context(
    drugs: list[str],
    evidence: list[dict],
    warnings: list[str],
    rule_findings: list[dict],
) -> str:
    """Compact context for the holistic prompt. `rule_findings` are RiskFinding
    dicts from state["risk_assessment"]."""
    parts: list[str] = [f"DRUGS IN REGIMEN: {', '.join(drugs) if drugs else 'none'}"]

    if rule_findings:
        parts.append("\nRULES ENGINE HITS (do not restate these):")
        for h in rule_findings:
            sev = h.get("severity", "")
            ds  = " + ".join(h.get("drugs") or [])
            parts.append(f"  - [{sev}] {ds} — {h.get('mechanism', '')}")

    found, cleared = [], []
    for row in evidence:
        if row.get("tool") == "check_interaction_pair":
            result = (row.get("result") or "").strip()
            (cleared if "No recorded interaction" in result else found).append(result)

    if found:
        parts.append("\nINTERACTIONS FOUND IN DATABASE:")
        parts.extend(f"  - {i}" for i in found)

    if cleared:
        parts.append("\nPAIRS CLEARED BY DATABASE ('no recorded interaction'):")
        parts.extend(f"  - {p}" for p in cleared)

    if warnings:
        parts.append("\nWARNINGS ALREADY GENERATED BY THE SYSTEM:")
        parts.extend(f"  - {w}" for w in warnings)

    return "\n".join(parts)


def _parse_alert_lines(text: str) -> list[dict]:
    """Parse pipe-delimited alert lines returned by the holistic check."""
    alerts: list[dict] = []
    for line in text.strip().split("\n"):
        line = line.strip()
        if not line or line.upper() == "NONE":
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 4:
            continue
        severity = parts[0].upper()
        if severity not in _SEVERITY_BADGE:
            continue
        alerts.append({
            "severity":       severity,
            "drugs":          parts[1],
            "mechanism":      parts[2],
            "recommendation": parts[3],
        })
    return alerts


# ── Evidence formatting ────────────────────────────────────────────────────────

def _format_article(evidence: list[dict]) -> str:
    """Build article text for per-claim verification.
    Pairwise rows come first so they are never crowded out by bulk lookups."""
    if not evidence:
        return ""
    sorted_rows = sorted(
        evidence,
        key=lambda r: _EVIDENCE_PRIORITY.get(r.get("tool", ""), 99),
    )
    parts: list[str] = []
    total = 0
    for row in sorted_rows:
        finding = (row.get("result") or "").strip()
        if not finding:
            continue
        if total + len(finding) > _MAX_ARTICLE_CHARS:
            remaining = _MAX_ARTICLE_CHARS - total
            if remaining > 100:
                parts.append(finding[:remaining])
            break
        parts.append(finding)
        total += len(finding) + 2
    return "\n\n".join(parts)


# ── Rendering ──────────────────────────────────────────────────────────────────

def _render_verification_section(results: list[dict]) -> str:
    """Per-claim verification table with severity column.
    Rows without a score are omitted; section is hidden if nothing scored."""
    scored = [r for r in results if r.get("score") is not None]
    if not scored:
        return ""
    lines = [
        "---",
        "",
        "## Independent Clinical Verification",
        "",
        "Each safety claim was independently scored against the retrieved evidence.",
        "",
        "| # | Claim | Score | Severity | Verdict |",
        "| --- | --- | --- | --- | --- |",
    ]
    for i, r in enumerate(scored, 1):
        score    = r["score"]
        severity = r.get("severity") or ""
        badge    = (f"{_SEVERITY_BADGE[severity]} {severity}" if severity in _SEVERITY_BADGE else "—")
        claim_text = (r.get("claim") or "").replace("|", "\\|").replace("\n", " ")
        if len(claim_text) > 140:
            claim_text = claim_text[:137] + "…"
        verdict = _VERDICT_LABEL.get(score, str(score))
        lines.append(f"| {i} | {claim_text} | {score:+d} | {badge} | {verdict} |")
    lines.append("")
    return "\n".join(lines)


_SEVERITY_TO_ROW_LABEL = {
    "LOW":      "🟢 Low Risk",
    "MEDIUM":   "🟡 Moderate Risk",
    "HIGH":     "🟠 High Risk",
    "CRITICAL": "🔴 Critical Risk",
}


def _rewrite_risk_level_row(text: str, severity_value: str) -> str:
    """Rewrite the `| **Risk Level** | ... |` row to reflect an escalated label
    coming from the post-verifier consistency check. No-op if the row is
    missing (the risk_engine already appended a stand-alone line in that case)."""
    label = _SEVERITY_TO_ROW_LABEL.get(severity_value, severity_value)
    new_row = f"| **Risk Level** | {label} |"
    lines = (text or "").split("\n")
    for i, line in enumerate(lines):
        if line.startswith("| **Risk Level**"):
            lines[i] = new_row
            return "\n".join(lines)
    return text


def _render_clinical_alerts_section(holistic: dict) -> str:
    """Physiological violations + missed interactions from holistic reasoning.
    Section is hidden when both lists are empty."""
    physio  = holistic.get("physiological_issues") or []
    missing = holistic.get("missing_interactions")  or []

    if not physio and not missing:
        return ""

    def _esc(s: str) -> str:
        return s.replace("|", "\\|")

    lines = [
        "---",
        "",
        "## Clinical Safety Alerts",
        "",
        "> ⚠️ The following risks were identified by independent clinical reasoning "
        "and may not be reflected in the drug-interaction database.",
        "",
    ]

    if physio:
        lines += [
            "### Physiological Rule Violations",
            "",
            "| Severity | Drug Pair | Mechanism | Recommendation |",
            "| --- | --- | --- | --- |",
        ]
        for a in physio:
            badge = f"{_SEVERITY_BADGE.get(a['severity'], '')} {a['severity']}"
            lines.append(
                f"| {badge} | {_esc(a['drugs'])} | {_esc(a['mechanism'])} | {_esc(a['recommendation'])} |"
            )
        lines.append("")

    if missing:
        lines += [
            "### Missed High-Risk Interactions",
            "",
            "| Severity | Drug Pair | Clinical Risk | Why Missed |",
            "| --- | --- | --- | --- |",
        ]
        for a in missing:
            badge = f"{_SEVERITY_BADGE.get(a['severity'], '')} {a['severity']}"
            lines.append(
                f"| {badge} | {_esc(a['drugs'])} | {_esc(a['mechanism'])} | {_esc(a['recommendation'])} |"
            )
        lines.append("")

    return "\n".join(lines)


# ── Node entry point ───────────────────────────────────────────────────────────

def _find_matching_rule(claim: str, rule_findings: list[dict]) -> dict | None:
    """Return the highest-severity rule finding whose drugs all appear in the
    claim text. Used to pin Pass-1 severity to deterministic output when a
    rule fires. Operates on RiskFinding dicts (serialised model_dump form)."""
    claim_lower = claim.lower()
    matches = [
        h for h in rule_findings
        if all(d.lower() in claim_lower for d in (h.get("drugs") or []))
    ]
    if not matches:
        return None
    return next(
        (h for h in matches if h.get("severity") == Severity.HIGH.value),
        matches[0],
    )


def clinical_verifier_node(state: AgentState) -> dict:
    """Three-pass clinical verifier.

    Pass 0 — rules engine: deterministic class-level checks.
    Pass 1 — per-claim: evidence scoring, direction validation, severity tagging
             (severity is overridden by Pass-0 when a rule matches the claim).
    Pass 2 — holistic LLM: residual physiological rules + negative-space gaps.
    """
    if state.get("blocked"):
        return {}

    start_time = time.time()

    if not settings.ENABLE_CLINICAL_VERIFICATION:
        trace = AgentTrace(
            agent=AGENT_NAME,
            action="claim_verification",
            summary="Verification disabled via settings.",
            duration_seconds=round(time.time() - start_time, 2),
        )
        return {"audit_log": [trace.model_dump()]}

    warnings     = state.get("safety_warnings")  or []
    evidence     = state.get("evidence")          or []
    drugs        = state.get("drugs_identified")  or []
    final_answer = state.get("final_answer")      or ""

    # ── Pass 0: pull findings from risk_engine ───────────────────────────────
    # The deterministic rules already ran in the risk_engine node; reuse its
    # findings rather than recomputing. Findings are RiskFinding dicts after
    # model_dump() — same shape regardless of source.
    risk_assessment = state.get("risk_assessment") or {}
    rule_findings: list[dict] = risk_assessment.get("findings") or []

    article = _format_article(evidence)

    # ── Pass 1: per-claim verification ────────────────────────────────────────
    pass1_results: list[dict] = []
    if warnings and article:
        for claim in warnings[:_MAX_CLAIMS]:
            outcome = _verify_claim(article, claim)
            rule = _find_matching_rule(claim, rule_findings)
            if rule is not None:
                # Map back to the legacy RED/ORANGE/GREEN strings the
                # _render_verification_section badge map expects.
                outcome["severity"] = _legacy_severity(rule.get("severity"))
                outcome["rule_id"]  = rule.get("rule_id")
            pass1_results.append({"claim": claim, **outcome})

    scored_scores  = [r["score"] for r in pass1_results if r.get("score") is not None]
    avg            = (sum(scored_scores) / len(scored_scores)) if scored_scores else None
    contradictions = sum(1 for s in scored_scores if s < 0)
    agreements     = sum(1 for s in scored_scores if s > 0)
    skipped        = len(warnings) - len(pass1_results)

    # ── Pass 2: holistic clinical reasoning (LLM, informed by Pass 0) ─────────
    holistic: dict = {"physiological_issues": [], "missing_interactions": [], "error": None}
    if drugs:
        holistic = _holistic_clinical_check(drugs, evidence, warnings, rule_findings)

    # The risk_engine has already rendered every rule-based finding in its
    # own "Comprehensive Risk Assessment" table — do not duplicate it here.
    # The verifier's clinical-alerts section now shows ONLY the LLM-derived
    # missing_interactions (Pass-2 negative-space).

    total_alerts = (
        len(holistic["physiological_issues"]) + len(holistic["missing_interactions"])
    )

    # ── Compose updated answer ────────────────────────────────────────────────
    updated_answer = final_answer
    verification_md = _render_verification_section(pass1_results)
    alerts_md       = _render_clinical_alerts_section(holistic)

    if verification_md:
        updated_answer += "\n\n" + verification_md
    if alerts_md:
        updated_answer += "\n\n" + alerts_md

    # ── Post-verifier consistency check (clinical signals only) ──────────────
    # The verifier just appended new prose. If that prose introduces a real
    # clinical high-risk token (black-box, renal impairment, contraindicated,
    # …) while the arbitrated severity is still LOW, escalate to MEDIUM so
    # the label stays consistent with the narrative.
    #
    # System-error tokens are no longer in scope here — clean fallback paths
    # don't emit them, and "tool failed" doesn't influence the clinical label
    # (it's owned by risk_engine.arbitrate based on findings + insufficient_
    # clinical_data only).
    escalated_severity: str | None = None
    if risk_assessment:
        current = risk_assessment.get("final_severity")
        new_tokens = arbitration._detect_contradictions(updated_answer)
        seen = set(risk_assessment.get("contradictions") or [])
        unseen = [t for t in new_tokens if t not in seen]
        if unseen and current == Severity.LOW.value:
            escalated_severity = Severity.MEDIUM.value
            risk_assessment = {
                **risk_assessment,
                "final_severity": escalated_severity,
                "contradictions": list(risk_assessment.get("contradictions") or []) + unseen,
            }
            updated_answer = _rewrite_risk_level_row(updated_answer, escalated_severity)

    # ── Audit trace ───────────────────────────────────────────────────────────
    summary_parts = [f"{len(scored_scores)}/{len(pass1_results)} scored"]
    if avg is not None:
        summary_parts.append(f"avg={avg:+.1f}")
    summary_parts.append(f"contradictions={contradictions}, agreements={agreements}")
    if rule_hits:
        summary_parts.append(f"rule_hits={len(rule_hits)}")
    if total_alerts:
        summary_parts.append(f"clinical_alerts={total_alerts}")
    if skipped:
        summary_parts.append(f"skipped={skipped}")

    duration = round(time.time() - start_time, 2)
    trace = AgentTrace(
        agent=AGENT_NAME,
        action="claim_verification",
        summary=", ".join(summary_parts),
        duration_seconds=duration,
        metadata={
            "pass1_results": pass1_results,
            "rule_hits":     [h.to_alert_dict() for h in rule_hits],
            "holistic":      holistic,
            "skipped":       skipped,
        },
    )
    logger.info("[%s] %s in %.1fs", AGENT_NAME, ", ".join(summary_parts), duration)

    result: dict = {
        "final_answer":           updated_answer,
        "verification_results":   pass1_results,
        "verification_avg_score": avg,
        "audit_log":              [trace.model_dump()],
    }
    if escalated_severity:
        result["risk_assessment"] = risk_assessment
        result["final_severity"]  = escalated_severity
    return result

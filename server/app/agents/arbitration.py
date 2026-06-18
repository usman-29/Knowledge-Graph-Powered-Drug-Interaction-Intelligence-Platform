"""Risk arbitration and contradiction detection.

The arbitration layer is the single source of truth for `final_severity`.
Its contract:

  - Severity is the MAX across clinical findings — never an average.
  - One severe finding dominates many neutral ones.
  - The label depends ONLY on clinical evidence (findings + narrative
    clinical signals). It does NOT depend on tool failures, parsing
    failures, or missing metadata.
  - When clinical reasoning could not produce any signal at all
    (`insufficient_clinical_data=True`), the safe-default is
    Severity.HIGH with `insufficient_data=True` — the report renders as
    "HIGH RISK – INSUFFICIENT DATA". This is distinct from a clinically-
    determined HIGH and is the only path that returns HIGH without a
    matching finding.

Pure functions; no LLM, no I/O.
"""
from __future__ import annotations

import re

from app.models.schemas import RiskAssessment, RiskFinding, Severity


_SEVERITY_RANK = {
    Severity.LOW: 0,
    Severity.MEDIUM: 1,
    Severity.HIGH: 2,
    Severity.CRITICAL: 3,
}


# Clinical narrative tokens whose presence implies the report describes a
# real clinical risk. If any of these appear in the rendered narrative while
# the computed severity is still LOW, the label is escalated to MEDIUM so
# the label and the prose don't contradict each other.
#
# Note: these are CLINICAL tokens only. System-error tokens ("could not be
# completed", "synthesis unavailable") never appear in user-facing output
# and never influence severity.
_HIGH_RISK_NARRATIVE_TOKENS = (
    r"\bblack[\s-]?box(?:ed)?\s+warning\b",
    r"\brenal\s+(?:impairment|failure|insufficiency)\b",
    r"\bheart\s+failure\s+(?:exacerbation|decompensation|worsening)\b",
    r"\bcontraindicat",
    r"\bnephrotoxic",
    r"\bhepatotoxic",
    r"\bteratogen",
    r"\blife[\s-]?threatening\b",
    r"\bserotonin\s+syndrome\b",
    r"\bqt\s+prolongation\b",
    r"\btorsade",
    r"\bhyperkalemia\b",
)


def arbitrate(
    findings: list[RiskFinding],
    narrative_text: str = "",
    insufficient_clinical_data: bool = False,
) -> RiskAssessment:
    """Collapse clinical findings into a single RiskAssessment.

    `insufficient_clinical_data` is set by the upstream node when no
    clinical signal could be produced (e.g. medical_agent crashed before
    extracting any drugs). It is the ONLY path that returns HIGH without
    a matching finding, and is rendered as "HIGH – INSUFFICIENT DATA".

    Tool/parsing failures that still let clinical rules run normally do
    NOT count as insufficient data — they don't influence the label.
    """
    deduped = _dedupe_by_rule(findings)
    contradictions = _detect_contradictions(narrative_text)

    if insufficient_clinical_data:
        return RiskAssessment(
            final_severity=Severity.HIGH,
            findings=deduped,
            contradictions=contradictions,
            insufficient_data=True,
        )

    final = _max_severity(deduped)
    if contradictions:
        final = max(final, Severity.MEDIUM, key=_SEVERITY_RANK.get)

    return RiskAssessment(
        final_severity=final,
        findings=deduped,
        contradictions=contradictions,
        insufficient_data=False,
    )


# ── Helpers ────────────────────────────────────────────────────────────────────

def _max_severity(findings: list[RiskFinding]) -> Severity:
    if not findings:
        return Severity.LOW
    return max((f.severity for f in findings), key=_SEVERITY_RANK.get)


def _dedupe_by_rule(findings: list[RiskFinding]) -> list[RiskFinding]:
    """Keep the highest-severity instance of each (rule_id, drug-set) pair."""
    bucket: dict[tuple[str, frozenset[str]], RiskFinding] = {}
    for f in findings:
        key = (f.rule_id, frozenset(d.lower() for d in f.drugs))
        existing = bucket.get(key)
        if existing is None or _SEVERITY_RANK[f.severity] > _SEVERITY_RANK[existing.severity]:
            bucket[key] = f
    return sorted(
        bucket.values(),
        key=lambda f: (-_SEVERITY_RANK[f.severity], f.domain, f.rule_id),
    )


def _detect_contradictions(text: str) -> list[str]:
    """Return any clinical high-risk narrative tokens present in `text`."""
    if not text:
        return []
    lowered = text.lower()
    matches: list[str] = []
    for pattern in _HIGH_RISK_NARRATIVE_TOKENS:
        m = re.search(pattern, lowered, re.IGNORECASE)
        if m:
            matches.append(m.group(0))
    return matches

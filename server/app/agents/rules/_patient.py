"""Patient-state predicates shared by every rule family.

The patient dict comes from chat.py via state["patient"]. Conditions are
free-form strings (e.g. "Chronic kidney disease", "CKD stage 3") — each
predicate matches a curated set of substrings so renaming a condition in
patients.json doesn't silently turn a HIGH finding into LOW.
"""
from __future__ import annotations

from typing import Any


_CKD_TERMS = (
    "chronic kidney disease", "ckd", "renal failure", "renal insufficiency",
    "kidney failure", "esrd", "end-stage renal", "dialysis",
)
_HF_TERMS = (
    "heart failure", "chf", "congestive heart failure", "cardiomyopathy",
    "reduced ejection fraction", "hfref", "hfpef",
)
_LIVER_TERMS = (
    "cirrhosis", "hepatic failure", "liver failure", "hepatic impairment",
    "child-pugh", "ascites", "hepatitis c", "alcoholic liver",
)
_PREGNANCY_TERMS = ("pregnancy", "pregnant", "gestational")
_CAD_TERMS = (
    "coronary artery disease", "cad", "ischemic heart disease",
    "prior myocardial infarction", "history of mi", "stable angina",
    "unstable angina",
)
_PUD_TERMS = (
    "peptic ulcer", "gi bleed", "gastrointestinal bleeding", "ulcer disease",
    "history of gi bleed",
)
_ASTHMA_TERMS = ("asthma", "reactive airway", "bronchospasm")
_HYPERKALEMIA_TERMS = ("hyperkalemia", "hyperkalaemia", "elevated potassium")
_EPILEPSY_TERMS = ("epilepsy", "seizure disorder", "seizures")


def _any_match(haystack: list[str], terms: tuple[str, ...]) -> bool:
    return any(t in (s or "").lower() for s in haystack for t in terms)


def conditions_of(patient: dict[str, Any] | None) -> list[str]:
    return list((patient or {}).get("conditions") or [])


def allergies_of(patient: dict[str, Any] | None) -> list[str]:
    return list((patient or {}).get("allergies") or [])


def age_of(patient: dict[str, Any] | None) -> int | None:
    age = (patient or {}).get("age")
    return int(age) if isinstance(age, (int, float)) else None


def has_ckd(patient: dict[str, Any] | None) -> bool:
    return _any_match(conditions_of(patient), _CKD_TERMS)


def has_heart_failure(patient: dict[str, Any] | None) -> bool:
    return _any_match(conditions_of(patient), _HF_TERMS)


def has_liver_disease(patient: dict[str, Any] | None) -> bool:
    return _any_match(conditions_of(patient), _LIVER_TERMS)


def is_pregnant(patient: dict[str, Any] | None) -> bool:
    return _any_match(conditions_of(patient), _PREGNANCY_TERMS)


def has_cad(patient: dict[str, Any] | None) -> bool:
    return _any_match(conditions_of(patient), _CAD_TERMS)


def has_pud_or_gib(patient: dict[str, Any] | None) -> bool:
    return _any_match(conditions_of(patient), _PUD_TERMS)


def has_asthma(patient: dict[str, Any] | None) -> bool:
    return _any_match(conditions_of(patient), _ASTHMA_TERMS)


def has_hyperkalemia(patient: dict[str, Any] | None) -> bool:
    return _any_match(conditions_of(patient), _HYPERKALEMIA_TERMS)


def has_epilepsy(patient: dict[str, Any] | None) -> bool:
    return _any_match(conditions_of(patient), _EPILEPSY_TERMS)


def is_elderly(patient: dict[str, Any] | None) -> bool:
    age = age_of(patient)
    return age is not None and age >= 65


def is_vulnerable(patient: dict[str, Any] | None) -> bool:
    """Aggregate flag used by the black-box amplifier."""
    return (
        is_elderly(patient)
        or has_ckd(patient)
        or has_heart_failure(patient)
        or has_liver_disease(patient)
        or is_pregnant(patient)
    )

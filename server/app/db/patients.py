"""
Synthetic patient store — loads data/patients.json on demand.

These are *synthetic* records (no real PII). The roster exists so clinicians
can demo the workflow of "look up an interaction for this specific patient"
without typing real identifiers into the chat.

Writes (add/remove medication) persist to the JSON file so changes survive a
process restart. The lru_cache is invalidated on every write.
"""
from __future__ import annotations

import json
import threading
from functools import lru_cache
from pathlib import Path

from app.config.settings import settings
from app.models.schemas import Medication, Patient, PatientSummary

# Single-process write lock — guards the JSON file against concurrent writes.
_write_lock = threading.Lock()


@lru_cache(maxsize=1)
def _load_patients() -> list[Patient]:
    """Parse the JSON file once per process — cache invalidates on restart
    or on any call to `_invalidate_cache()` after a write."""
    path = Path(settings.PATIENTS_FILE)
    if not path.exists():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [Patient.model_validate(item) for item in raw]


def _invalidate_cache() -> None:
    _load_patients.cache_clear()


def _write_patients(patients: list[Patient]) -> None:
    """Atomically rewrite the JSON store, then clear the cache."""
    path = Path(settings.PATIENTS_FILE)
    payload = [p.model_dump() for p in patients]
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(path)
    _invalidate_cache()


def list_patients() -> list[PatientSummary]:
    return [
        PatientSummary(
            id=p.id,
            display_name=p.display_name,
            age=p.age,
            sex=p.sex,
            medication_count=len(p.medications),
            primary_condition=p.conditions[0] if p.conditions else None,
        )
        for p in _load_patients()
    ]


def get_patient(patient_id: str) -> Patient | None:
    for p in _load_patients():
        if p.id == patient_id:
            return p
    return None


def add_medication(patient_id: str, medication: Medication) -> Patient | None:
    """Append a medication to a patient's regimen. Idempotent: if a medication
    with the same name already exists, returns the patient unchanged.
    Returns None if the patient doesn't exist."""
    with _write_lock:
        patients = list(_load_patients())
        target = next((p for p in patients if p.id == patient_id), None)
        if target is None:
            return None

        normalized = medication.name.strip().lower()
        if any(m.name.strip().lower() == normalized for m in target.medications):
            return target

        target.medications.append(medication)
        _write_patients(patients)
        return target


def remove_medication(patient_id: str, medication_name: str) -> Patient | None:
    """Remove a medication by name (case-insensitive). Returns the updated
    patient, or None if the patient doesn't exist. If the medication isn't on
    the regimen, returns the patient unchanged."""
    with _write_lock:
        patients = list(_load_patients())
        target = next((p for p in patients if p.id == patient_id), None)
        if target is None:
            return None

        normalized = medication_name.strip().lower()
        before = len(target.medications)
        target.medications = [
            m for m in target.medications if m.name.strip().lower() != normalized
        ]
        if len(target.medications) != before:
            _write_patients(patients)
        return target

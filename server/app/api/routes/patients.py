"""Patient roster endpoints — read access plus medication add/remove writes."""
from fastapi import APIRouter, HTTPException

from app.db.patients import (
    add_medication,
    get_patient,
    list_patients,
    remove_medication,
)
from app.models.schemas import Medication, Patient, PatientSummary

router = APIRouter(prefix="/patients", tags=["patients"])


@router.get("", response_model=list[PatientSummary])
def get_all() -> list[PatientSummary]:
    return list_patients()


@router.get("/{patient_id}", response_model=Patient)
def get_one(patient_id: str) -> Patient:
    patient = get_patient(patient_id)
    if patient is None:
        raise HTTPException(status_code=404, detail=f"Patient {patient_id} not found")
    return patient


@router.post("/{patient_id}/medications", response_model=Patient)
def add_med(patient_id: str, medication: Medication) -> Patient:
    """Add a medication to a patient's regimen. Idempotent on medication name."""
    updated = add_medication(patient_id, medication)
    if updated is None:
        raise HTTPException(status_code=404, detail=f"Patient {patient_id} not found")
    return updated


@router.delete("/{patient_id}/medications/{medication_name}", response_model=Patient)
def remove_med(patient_id: str, medication_name: str) -> Patient:
    """Remove a medication from a patient's regimen, matched case-insensitively
    by name."""
    updated = remove_medication(patient_id, medication_name)
    if updated is None:
        raise HTTPException(status_code=404, detail=f"Patient {patient_id} not found")
    return updated

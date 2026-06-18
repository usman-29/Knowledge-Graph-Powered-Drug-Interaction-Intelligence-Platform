"""
Ontology helpers used by the risk engine.

Two responsibilities:

1. Drug-class membership — map a free-form drug name to one or more
   pharmacologic classes (NSAID, ACE inhibitor, etc.). This is what makes
   class-level rules work: a rule about NSAIDs fires for ketorolac because
   ketorolac ∈ NSAID, even when the DDI database has nothing on it.

2. Allergy / agent expansion — expand free-form allergy text and exposure
   terms to a normalized set of equivalent terms so cross-reactivity checks
   don't depend on exact string matches. "Iodinated contrast", "contrast
   dye", "iodine contrast" all collapse to a single canonical agent.

Hardcoded synonyms are the floor; SNOMED IS_A lookup against the loaded
:SnomedConcept graph is layered on top as best-effort enrichment. A SNOMED
miss is NOT silent — it returns an `uncertain=True` flag so the risk engine
can escalate caution rather than reduce risk (requirement #5).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from app.db.neo4j import db_manager


# ── Drug class membership ─────────────────────────────────────────────────────
#
# Single source of truth for pharmacologic class membership. All names are
# lower-cased; matching is case-insensitive. Synonyms / brand names are
# deliberately omitted — upstream normalisation should resolve to the generic.

_CORE_DRUG_CLASSES: dict[str, set[str]] = {
    "k_sparing_diuretic": {
        "spironolactone", "eplerenone", "amiloride", "triamterene",
    },
    "k_supplement": {
        "potassium chloride", "potassium gluconate", "potassium citrate",
        "potassium phosphate", "potassium bicarbonate",
    },
    "ace_inhibitor": {
        "lisinopril", "enalapril", "ramipril", "captopril", "benazepril",
        "quinapril", "perindopril", "fosinopril", "trandolapril",
    },
    "arb": {
        "losartan", "valsartan", "irbesartan", "candesartan",
        "olmesartan", "telmisartan", "azilsartan",
    },
    "loop_diuretic": {
        "furosemide", "bumetanide", "torsemide", "ethacrynic acid",
    },
    "thiazide_diuretic": {
        "hydrochlorothiazide", "chlorthalidone", "indapamide",
        "metolazone", "chlorothiazide",
    },
    "narrow_ti": {
        "digoxin", "warfarin", "lithium", "phenytoin",
        "carbamazepine", "theophylline", "tacrolimus", "cyclosporine",
    },
    "qt_prolonger": {
        "amiodarone", "sotalol", "dofetilide", "ibutilide", "quinidine",
        "procainamide", "disopyramide", "citalopram", "escitalopram",
        "ondansetron", "methadone", "ciprofloxacin", "levofloxacin",
        "moxifloxacin", "azithromycin", "erythromycin", "clarithromycin",
        "haloperidol", "risperidone", "ziprasidone", "thioridazine",
    },
    "nsaid": {
        "ibuprofen", "naproxen", "diclofenac", "ketorolac",
        "celecoxib", "meloxicam", "indomethacin", "piroxicam",
    },
    "anticoagulant": {
        "warfarin", "apixaban", "rivaroxaban", "dabigatran", "edoxaban",
        "heparin", "enoxaparin", "dalteparin", "fondaparinux",
    },
    "antiplatelet": {
        "aspirin", "clopidogrel", "ticagrelor", "prasugrel", "dipyridamole",
    },
    "digoxin": {"digoxin"},
}


_EXTRA_DRUG_CLASSES: dict[str, set[str]] = {
    "metformin":          {"metformin"},
    "sulfonylurea":       {"glipizide", "glyburide", "glimepiber", "glimepiride"},
    "benzodiazepine":     {
        "diazepam", "lorazepam", "alprazolam", "clonazepam", "temazepam",
        "oxazepam", "midazolam", "triazolam", "chlordiazepoxide",
    },
    "first_gen_antihistamine": {
        "diphenhydramine", "hydroxyzine", "chlorpheniramine", "promethazine",
        "doxylamine", "meclizine",
    },
    "muscle_relaxant_anticholinergic": {
        "cyclobenzaprine", "carisoprodol", "methocarbamol", "metaxalone",
        "orphenadrine",
    },
    "tricyclic_antidepressant": {
        "amitriptyline", "nortriptyline", "imipramine", "desipramine",
        "doxepin", "clomipramine",
    },
    "z_drug": {"zolpidem", "zaleplon", "eszopiclone"},
    "iodinated_contrast": {
        "iohexol", "iopamidol", "iodixanol", "ioversol", "iopromide",
        "diatrizoate", "ioxilan", "iothalamate",
    },
    "ssri": {
        "fluoxetine", "sertraline", "paroxetine", "citalopram", "escitalopram",
        "fluvoxamine",
    },
    "snri": {"venlafaxine", "duloxetine", "desvenlafaxine", "milnacipran"},
    "maoi": {"phenelzine", "tranylcypromine", "isocarboxazid", "selegiline"},
    "triptan": {
        "sumatriptan", "rizatriptan", "zolmitriptan", "eletriptan",
        "naratriptan", "almotriptan", "frovatriptan",
    },
    "sulfa_antibiotic": {
        "sulfamethoxazole", "sulfadiazine", "sulfisoxazole",
        "trimethoprim-sulfamethoxazole", "tmp-smx", "bactrim",
    },
    "penicillin": {
        "amoxicillin", "ampicillin", "penicillin", "penicillin v",
        "penicillin g", "dicloxacillin", "nafcillin", "oxacillin",
        "piperacillin", "ticarcillin",
    },
    "cephalosporin": {
        "cefazolin", "cephalexin", "cefuroxime", "ceftriaxone", "cefepime",
        "cefotaxime", "cefdinir", "cefpodoxime", "cefaclor",
    },
    "ace_inhibitor_in_pregnancy_class": _CORE_DRUG_CLASSES["ace_inhibitor"],
    "arb_in_pregnancy_class":          _CORE_DRUG_CLASSES["arb"],
    "statin": {
        "atorvastatin", "simvastatin", "rosuvastatin", "pravastatin",
        "lovastatin", "fluvastatin", "pitavastatin",
    },
}

# Union of the core pharmacologic classes and the risk-engine extras.
DRUG_CLASSES: dict[str, set[str]] = {
    **_CORE_DRUG_CLASSES,
    **_EXTRA_DRUG_CLASSES,
}


# ── Allergy / agent synonyms ──────────────────────────────────────────────────
#
# Each canonical agent maps to a set of free-form spellings clinicians and
# patients actually use. Lookups normalise both sides (lowercase + strip).
# The canonical key is what rules check exposure against.

ALLERGY_SYNONYMS: dict[str, set[str]] = {
    "iodinated_contrast": {
        "iodine", "iodinated", "iodinated contrast", "contrast", "contrast dye",
        "contrast media", "contrast agent", "iodine contrast", "iodinated dye",
        "radiocontrast", "x-ray dye", "ct contrast", "iv contrast",
    },
    "aspirin": {
        "aspirin", "asa", "acetylsalicylic acid", "salicylate", "salicylates",
    },
    "nsaid": {
        "nsaid", "nsaids", "non-steroidal anti-inflammatory",
        "non steroidal anti inflammatory", "ibuprofen", "naproxen",
    },
    "penicillin": {
        "penicillin", "penicillins", "pcn", "amoxicillin", "ampicillin",
        "beta-lactam", "beta lactam",
    },
    "sulfa": {
        "sulfa", "sulfa drugs", "sulphonamide", "sulfonamide", "sulphonamides",
        "sulfonamides", "bactrim", "trimethoprim-sulfamethoxazole",
    },
    "shellfish": {"shellfish", "shrimp", "crustacean", "crustaceans"},
    "latex": {"latex", "natural rubber latex"},
    "codeine": {"codeine", "opiate (codeine)"},
}


# ── Public helpers ────────────────────────────────────────────────────────────

@dataclass
class AgentMatch:
    """Result of mapping a free-form allergy/exposure term to a canonical agent.

    `uncertain=True` means no canonical match was found; the caller should
    escalate caution rather than silently treat the term as safe.
    """
    canonical: str | None
    raw: str
    uncertain: bool


def _norm(s: str) -> str:
    return (s or "").lower().strip()


def classes_for(drug: str) -> set[str]:
    """Return every class `drug` belongs to. Empty set if unknown."""
    n = _norm(drug)
    return {cls for cls, members in DRUG_CLASSES.items() if n in members}


def drugs_in_class(drugs: Iterable[str], class_name: str) -> list[str]:
    """Filter `drugs` to those in `class_name`, preserving original casing."""
    members = DRUG_CLASSES.get(class_name, set())
    return [d for d in drugs if _norm(d) in members]


def has_class(drugs: Iterable[str], class_name: str) -> bool:
    return bool(drugs_in_class(drugs, class_name))


def normalise_allergy(term: str) -> AgentMatch:
    """Map a free-form allergy term to a canonical agent.

    Resolution order:
      1. Direct synonym table (cheap, deterministic).
      2. SNOMED IS_A lookup against the loaded :SnomedConcept graph.
      3. Give up — return uncertain=True so the risk engine can escalate.
    """
    n = _norm(term)
    if not n:
        return AgentMatch(canonical=None, raw=term, uncertain=True)

    for canonical, synonyms in ALLERGY_SYNONYMS.items():
        if n in synonyms:
            return AgentMatch(canonical=canonical, raw=term, uncertain=False)

    snomed_hit = _snomed_lookup(n)
    if snomed_hit is not None:
        return AgentMatch(canonical=snomed_hit, raw=term, uncertain=False)

    return AgentMatch(canonical=None, raw=term, uncertain=True)


def expand_exposure_to_agents(drugs: Iterable[str]) -> set[str]:
    """Map a drug list to the set of canonical allergy-agent keys those drugs
    represent. Used to check whether the regimen exposes a known allergy."""
    agents: set[str] = set()
    for drug in drugs:
        n = _norm(drug)
        # Direct synonym membership (e.g. "aspirin" → "aspirin")
        for canonical, synonyms in ALLERGY_SYNONYMS.items():
            if n in synonyms:
                agents.add(canonical)
        # Class-based exposure (e.g. ketorolac ∈ NSAID → "nsaid" agent)
        for cls in classes_for(drug):
            if cls in ALLERGY_SYNONYMS:
                agents.add(cls)
        # Iodinated-contrast members route via the explicit class
        if n in DRUG_CLASSES.get("iodinated_contrast", set()):
            agents.add("iodinated_contrast")
    return agents


# ── SNOMED fallback ───────────────────────────────────────────────────────────

# Mapping from SNOMED FSN substrings to canonical allergy agents. Only used
# when the direct synonym table misses. Keys are lowercase substrings.
_SNOMED_FSN_HINTS: dict[str, str] = {
    "iodinated":  "iodinated_contrast",
    "contrast":   "iodinated_contrast",
    "penicillin": "penicillin",
    "cephalosporin": "penicillin",
    "sulfonamide": "sulfa",
    "salicylate": "aspirin",
}


def _snomed_lookup(term: str) -> str | None:
    """Best-effort SNOMED enrichment: find a SnomedConcept whose FSN contains
    the term, then walk one IS_A hop up looking for an FSN hint that points to
    a canonical agent. Returns None on any miss; never raises."""
    try:
        rows = db_manager.execute_query(
            "MATCH (c:SnomedConcept) "
            "WHERE toLower(c.fsn) CONTAINS $term "
            "OPTIONAL MATCH (c)-[:IS_A]->(p:SnomedConcept) "
            "RETURN c.fsn AS fsn, collect(p.fsn) AS parents LIMIT 5",
            {"term": term},
        )
    except Exception:
        return None

    for row in rows or []:
        candidates = [row.get("fsn") or ""] + list(row.get("parents") or [])
        for fsn in candidates:
            fsn_lower = (fsn or "").lower()
            for hint, canonical in _SNOMED_FSN_HINTS.items():
                if hint in fsn_lower:
                    return canonical
    return None

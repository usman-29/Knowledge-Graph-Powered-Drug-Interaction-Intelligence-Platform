"""
CLI entry point for all knowledge-graph ingestion jobs.

Usage from the `server/` directory:

    python -m app.db.run_ingestion drugs       # Kaggle DDI CSV → :Drug nodes + INTERACTS_WITH
    python -m app.db.run_ingestion rxnorm      # RxNorm RRF → :Concept nodes + MAPS_TO links
    python -m app.db.run_ingestion snomed      # SNOMED CT RF2 → :SnomedConcept + IS_A
    python -m app.db.run_ingestion all         # run every job in dependency order

Each subcommand is idempotent — re-running merges, never duplicates.
"""
from __future__ import annotations

import argparse
import sys

from app.db.ingestion import MedicalDataIngestor
from app.db.normalizer import RxNormNormalizer
from app.db.snomed import SnomedIngestor


DEFAULT_PATHS = {
    "drugs_csv": "data/raw/db_drug_interactions.csv",
    "rxnorm_rrf": "data/raw/rxnorm/RXNCONSO.RRF",
    "snomed_dir": "data/raw/snomed",
}


def run_drugs(path: str) -> None:
    MedicalDataIngestor.ingest_drug_interactions(path)


def run_rxnorm(path: str) -> None:
    RxNormNormalizer(path).normalize_existing_drugs()


def run_snomed(path: str, full: bool = False) -> None:
    ingestor = SnomedIngestor(path)
    if full:
        ingestor.ingest_all()
    else:
        ingestor.ingest_drug_safety_subset()


def run_all(full_snomed: bool = True) -> None:
    """Ingest in dependency order: drug interactions first (creates :Drug
    nodes), then RxNorm (links :Drug → :Concept), then SNOMED.

    `full_snomed` defaults to True — local Neo4j has no node cap, so the
    full ~600K-concept RF2 snapshot is loaded. Pass False (or `--subset` on
    the CLI) to fall back to the drug-safety subset used for free-tier Aura.
    """
    run_drugs(DEFAULT_PATHS["drugs_csv"])
    run_rxnorm(DEFAULT_PATHS["rxnorm_rrf"])
    run_snomed(DEFAULT_PATHS["snomed_dir"], full=full_snomed)


def main() -> int:
    parser = argparse.ArgumentParser(prog="run_ingestion")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_drugs = sub.add_parser("drugs", help="Kaggle drug-drug interactions CSV")
    p_drugs.add_argument("--path", default=DEFAULT_PATHS["drugs_csv"])

    p_rx = sub.add_parser("rxnorm", help="RxNorm RXNCONSO.RRF normalization")
    p_rx.add_argument("--path", default=DEFAULT_PATHS["rxnorm_rrf"])

    p_sn = sub.add_parser("snomed", help="SNOMED CT RF2 snapshot directory")
    p_sn.add_argument("--path", default=DEFAULT_PATHS["snomed_dir"])
    p_sn.add_argument(
        "--full",
        action="store_true",
        help="Ingest all ~600K concepts (requires Neo4j paid tier). "
             "Default: drug-safety subset only (free-tier safe).",
    )

    p_all = sub.add_parser("all", help="Run every ingestion job in dependency order")
    p_all.add_argument(
        "--subset",
        action="store_true",
        help="Use the SNOMED drug-safety subset instead of the full ~600K-concept "
             "snapshot. Default is full ingestion (local Neo4j has no node cap).",
    )

    args = parser.parse_args()
    dispatch = {
        "drugs": lambda: run_drugs(args.path),
        "rxnorm": lambda: run_rxnorm(args.path),
        "snomed": lambda: run_snomed(args.path, full=getattr(args, "full", False)),
        "all": lambda: run_all(full_snomed=not getattr(args, "subset", False)),
    }
    dispatch[args.cmd]()
    return 0


if __name__ == "__main__":
    sys.exit(main())

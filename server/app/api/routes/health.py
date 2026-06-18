"""Liveness, Neo4j, and Veea proxy connectivity probes."""
from __future__ import annotations

import requests
from fastapi import APIRouter

from app.config.settings import settings
from app.db.neo4j import db_manager

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict:
    return {"status": "ok"}


@router.get("/health/db")
def health_db() -> list[dict]:
    return db_manager.execute_query("RETURN 'Neo4j connected' AS msg")


@router.get("/health/proxy")
def health_proxy() -> dict:
    """Verify that the Veea/Lobster Trap proxy is reachable on VEEA_ENDPOINT.

    Makes a minimal /models request to the proxy and reports whether the
    connection succeeded. This is the quickest way to confirm that LLM traffic
    is actually routing through the proxy during a demo.
    """
    models_url = settings.VEEA_ENDPOINT.rstrip("/").removesuffix("/v1") + "/v1/models"
    try:
        r = requests.get(
            models_url,
            headers={"Authorization": f"Bearer {settings.HUGGINGFACE_TOKEN}"},
            timeout=5.0,
        )
        reachable = r.status_code < 500
        return {
            "proxy_endpoint": settings.VEEA_ENDPOINT,
            "reachable": reachable,
            "http_status": r.status_code,
            "note": (
                "Proxy is reachable — LLM traffic is routing through Lobster Trap."
                if reachable
                else "Proxy returned a server error. Check that `lobstertrap serve` is running."
            ),
        }
    except requests.exceptions.ConnectionError:
        return {
            "proxy_endpoint": settings.VEEA_ENDPOINT,
            "reachable": False,
            "http_status": None,
            "note": "Cannot connect. Run: ./lobstertrap/lobstertrap serve --config configs/lobster_policy.yaml",
        }
    except Exception as exc:
        return {
            "proxy_endpoint": settings.VEEA_ENDPOINT,
            "reachable": False,
            "http_status": None,
            "note": f"Unexpected error: {exc}",
        }

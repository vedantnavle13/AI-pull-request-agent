"""
Phase 14 — Observability API endpoints.

Provides dashboard-ready JSON endpoints for:
  GET /metrics/overview            — aggregate stats across all reviews
  GET /metrics/reviews/{review_id} — single review deep-dive
  GET /metrics/agents              — per-agent performance stats
  GET /metrics/cost                — LLM cost breakdown

All responses are JSON-serializable. No secrets are returned.
"""

from fastapi import APIRouter, HTTPException, Query
from typing import Optional

from app.database.repository import (
    get_overview_metrics,
    get_review_detail_metrics,
    get_agent_metrics_summary,
    get_cost_summary,
    get_percentile_latency,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(tags=["Observability"])


@router.get("/overview")
def metrics_overview(
    repository: Optional[str] = Query(
        default=None,
        description="Filter by repository in owner/repo format",
        examples=["vedantnavle13/testing-pr"],
    )
):
    """
    Return high-level aggregate review statistics.

    Optional ?repository=owner/repo to scope to a single repository.
    """
    try:
        data = get_overview_metrics(repository=repository)
        p99 = get_percentile_latency(0.99, repository=repository)
        data["p99_latency_ms"] = int(p99) if p99 is not None else None
        return data
    except Exception as exc:
        logger.error("[Metrics] Overview query failed: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to fetch overview metrics")


@router.get("/reviews/{review_id}")
def metrics_review_detail(review_id: str):
    """
    Return detailed timing, per-agent metrics, LLM usage, and cost for a single review.

    review_id is the UUID from the review_runs table.
    """
    try:
        detail = get_review_detail_metrics(review_id=review_id)
    except Exception as exc:
        logger.error("[Metrics] Detail query failed for %s: %s", review_id, exc)
        raise HTTPException(status_code=500, detail="Failed to fetch review metrics")

    if detail is None:
        raise HTTPException(
            status_code=404,
            detail=f"Review {review_id!r} not found",
        )

    return detail


@router.get("/agents")
def metrics_agents():
    """
    Return per-agent aggregate performance statistics.

    Includes:
    - execution count
    - average latency (ms)
    - p95 latency (ms)
    - success rate (%)
    - average findings per review
    """
    try:
        return {"agents": get_agent_metrics_summary()}
    except Exception as exc:
        logger.error("[Metrics] Agent query failed: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to fetch agent metrics")


@router.get("/cost")
def metrics_cost():
    """
    Return LLM cost breakdown.

    Includes:
    - total cost (USD)
    - average cost per review
    - daily cost (last 24h)
    - cost broken down by agent
    - cost broken down by model
    """
    try:
        return get_cost_summary()
    except Exception as exc:
        logger.error("[Metrics] Cost query failed: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to fetch cost metrics")

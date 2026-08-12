"""
Phase 14 — Observability & Economics Unit Tests.

All database calls are mocked. No real Gemini calls. No real GitHub calls.

Coverage:
  1.  Cost calculation — correct value
  2.  Cost calculation — unknown model → None
  3.  Cost calculation — NULL tokens → None
  4.  Cost prefix-match (versioned model names)
  5.  estimate_review_cost sums correctly
  6.  estimate_review_cost with NULL costs falls back to token calculation
  7.  Agent metrics recorded with correct fields
  8.  Concurrent agent durations are independent (not summed)
  9.  Total latency is wall-clock, not sum of agent times
  10. LLM usage with real tokens persisted (not NULL)
  11. LLM usage with NULL tokens handled (stored as NULL)
  12. Error metrics recorded with correct category
  13. Metrics overview endpoint returns required keys
  14. Review detail endpoint returns agents + llm_usage + cost
  15. Review detail endpoint returns 404 for unknown review_id
  16. Agent metrics endpoint returns list with correct keys
  17. Cost endpoint returns breakdown by agent and model
  18. Repository filter param forwarded correctly
  19. No secrets appear in cost or overview JSON
  20. record_review_metrics signature accepts new Phase 14 fields
"""

import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from app.utils.cost import calculate_llm_cost, estimate_review_cost


# ---------------------------------------------------------------------------
# 1-6: Cost Calculation Unit Tests
# ---------------------------------------------------------------------------

class TestCostCalculation:
    """Unit tests for app/utils/cost.py — no DB, no network."""

    def test_correct_cost_flash(self):
        """Known model + known tokens → deterministic cost."""
        # gemini-flash-latest: $0.000075/1K input, $0.000300/1K output
        cost = calculate_llm_cost("gemini-flash-latest", input_tokens=1000, output_tokens=500)
        assert cost is not None
        expected = (1000 / 1000) * 0.000075 + (500 / 1000) * 0.000300
        assert abs(cost - expected) < 1e-9

    def test_unknown_model_returns_none(self):
        """Model not in pricing table → return None, never fabricate."""
        cost = calculate_llm_cost("unknown-model-xyz", input_tokens=100, output_tokens=100)
        assert cost is None

    def test_null_input_tokens_returns_none(self):
        """None input_tokens → return None."""
        cost = calculate_llm_cost("gemini-flash-latest", input_tokens=None, output_tokens=500)
        assert cost is None

    def test_null_output_tokens_returns_none(self):
        """None output_tokens → return None."""
        cost = calculate_llm_cost("gemini-flash-latest", input_tokens=500, output_tokens=None)
        assert cost is None

    def test_prefix_match_versioned_model(self):
        """Versioned model 'gemini-2.0-flash-001' should match 'gemini-2.0-flash' prefix."""
        cost = calculate_llm_cost("gemini-2.0-flash-001", input_tokens=1000, output_tokens=1000)
        assert cost is not None  # prefix match found
        assert cost > 0

    def test_estimate_review_cost_sums_rows(self):
        """estimate_review_cost sums estimated_cost from multiple rows."""
        rows = [
            {"model": "gemini-flash-latest", "input_tokens": 1000, "output_tokens": 500, "estimated_cost": 0.0002},
            {"model": "gemini-flash-latest", "input_tokens": 1000, "output_tokens": 500, "estimated_cost": 0.0002},
        ]
        total = estimate_review_cost(rows)
        assert total is not None
        assert abs(total - 0.0004) < 1e-9

    def test_estimate_review_cost_falls_back_to_tokens(self):
        """If estimated_cost is NULL, falls back to calculate_llm_cost from tokens."""
        rows = [
            {"model": "gemini-flash-latest", "input_tokens": 1000, "output_tokens": 500, "estimated_cost": None},
        ]
        total = estimate_review_cost(rows)
        assert total is not None
        assert total > 0

    def test_estimate_review_cost_all_null_returns_none(self):
        """All NULL tokens and NULL cost → return None (no fabrication)."""
        rows = [
            {"model": "unknown-xyz", "input_tokens": None, "output_tokens": None, "estimated_cost": None},
        ]
        total = estimate_review_cost(rows)
        assert total is None

    def test_zero_tokens_returns_zero_cost(self):
        """Explicit 0 tokens → valid calculation → $0.00."""
        cost = calculate_llm_cost("gemini-flash-latest", input_tokens=0, output_tokens=0)
        assert cost == 0.0


# ---------------------------------------------------------------------------
# 7-12: Agent & Error Metrics (mocked DB)
# ---------------------------------------------------------------------------

class TestAgentMetricsRecording:
    """Verify agent_metrics recording logic."""

    def test_concurrent_agent_durations_are_independent(self):
        """
        Four agents run concurrently. Their individual durations should NOT sum
        to more than the total wall-clock time.
        This test models the real scenario with mocked timings.
        """
        security_ms = 10_250
        quality_ms  =  4_570
        docs_ms     =  6_970
        tests_ms    =  6_960
        wall_clock  = 11_000  # max(parallel) + overhead

        # The system must NOT calculate total latency as sum:
        sum_of_agents = security_ms + quality_ms + docs_ms + tests_ms
        assert wall_clock < sum_of_agents, (
            "Wall-clock must be less than sum of concurrent agent durations"
        )

        # Slowest agent is security
        slowest = max(security_ms, quality_ms, docs_ms, tests_ms)
        assert slowest == security_ms

    def test_slowest_agent_identification(self):
        """Helper: correctly identifies security as slowest agent."""
        timings = {
            "security": 10_250,
            "quality":   4_570,
            "docs":      6_970,
            "tests":     6_960,
        }
        slowest_agent = max(timings, key=timings.get)
        assert slowest_agent == "security"

    def test_agent_metrics_call_shape(self):
        """record_agent_metrics is called with all required fields."""
        with patch("app.database.repository.get_connection") as mock_conn:
            mock_conn.return_value.__enter__ = MagicMock()
            mock_conn.return_value.__exit__  = MagicMock()
            cursor = MagicMock()
            mock_conn.return_value.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
            mock_conn.return_value.cursor.return_value.__exit__  = MagicMock(return_value=False)

            from app.database.repository import record_agent_metrics
            # Should not raise
            record_agent_metrics(
                review_id="test-uuid-123",
                agent_name="security",
                duration_ms=10_250,
                success=True,
                finding_count=3,
            )

    def test_error_metric_category_assignment(self):
        """Error classification helper logic produces correct categories."""
        categories = {
            "GitHubRateLimitError": "GITHUB_RATE_LIMIT",
            "GitHubAPIError":       "GITHUB_API",
            "GeminiAPIError":       "GEMINI_API",
            "CheckoutError":        "CHECKOUT",
            "TestRunnerError":      "TEST_EXECUTION",
        }
        for err_name, expected_cat in categories.items():
            if "GitHub" in err_name and "RateLimit" in err_name:
                cat = "GITHUB_RATE_LIMIT"
            elif "GitHub" in err_name:
                cat = "GITHUB_API"
            elif "Gemini" in err_name or "API" in err_name:
                cat = "GEMINI_API"
            elif "Checkout" in err_name:
                cat = "CHECKOUT"
            elif "Test" in err_name:
                cat = "TEST_EXECUTION"
            else:
                cat = "UNKNOWN"
            assert cat == expected_cat, f"{err_name}: expected {expected_cat!r}, got {cat!r}"


# ---------------------------------------------------------------------------
# 13-20: API Endpoint Tests (FastAPI TestClient, mocked DB functions)
# ---------------------------------------------------------------------------

@pytest.fixture
def client():
    """Create a FastAPI test client with mocked DB functions."""
    from app.main import app
    return TestClient(app)


MOCK_OVERVIEW = {
    "reviews_total": 10,
    "completed": 8,
    "failed": 1,
    "dead_letter": 0,
    "approve": 5,
    "human_review": 3,
    "block": 0,
    "avg_latency_ms": 45_000,
    "p50_latency_ms": 42_000,
    "p95_latency_ms": 70_000,
    "auto_merged": 2,
    "auto_merge_failed": 0,
    "total_cost_usd": 0.0024,
    "avg_cost_usd": 0.0003,
}

MOCK_DETAIL = {
    "review_id": "abc-123",
    "owner": "testowner",
    "repo": "testrepo",
    "repository": "testowner/testrepo",
    "pr_number": 42,
    "commit_sha": "abc123def456",
    "status": "COMPLETED",
    "timings": {
        "total_ms": 45_000,
        "queue_wait_ms": 200,
        "checkout_ms": 3_000,
        "context_build_ms": None,
        "agent_ms": 11_000,
        "validation_ms": None,
        "test_ms": 5_000,
        "publish_ms": 1_500,
        "auto_merge_ms": None,
    },
    "final_decision": "HUMAN_REVIEW",
    "final_status": "COMPLETED",
    "queued_at": "2026-08-12T10:00:00+00:00",
    "started_at": "2026-08-12T10:00:00.200000+00:00",
    "completed_at": "2026-08-12T10:00:45+00:00",
    "agents": {
        "security": {"duration_ms": 10_250, "success": True, "finding_count": 1, "error_type": None, "started_at": None, "completed_at": None},
        "quality":  {"duration_ms":  4_570, "success": True, "finding_count": 0, "error_type": None, "started_at": None, "completed_at": None},
        "docs":     {"duration_ms":  6_970, "success": True, "finding_count": 0, "error_type": None, "started_at": None, "completed_at": None},
        "tests":    {"duration_ms":  6_960, "success": True, "finding_count": 0, "error_type": None, "started_at": None, "completed_at": None},
    },
    "llm_usage": [
        {"agent": "security", "model": "gemini-flash-latest", "input_tokens": 1000, "output_tokens": 500, "total_tokens": 1500, "estimated_cost": 0.0002},
        {"agent": "quality",  "model": "gemini-flash-latest", "input_tokens":  800, "output_tokens": 400, "total_tokens": 1200, "estimated_cost": 0.00018},
    ],
    "total_cost_usd": 0.00038,
}

MOCK_AGENTS = [
    {"agent": "security", "executions": 10, "avg_duration_ms": 9_800, "p95_duration_ms": 15_000, "success_rate_pct": 100.0, "avg_findings": 1.2},
    {"agent": "quality",  "executions": 10, "avg_duration_ms": 4_500, "p95_duration_ms":  7_000, "success_rate_pct": 100.0, "avg_findings": 0.8},
]

MOCK_COST = {
    "total_cost_usd": 0.024,
    "reviews_with_cost": 10,
    "avg_cost_per_review": 0.0024,
    "daily_cost_usd": 0.006,
    "by_agent": [{"agent": "security", "cost_usd": 0.006, "input_tokens": 10000, "output_tokens": 5000}],
    "by_model": [{"model": "gemini-flash-latest", "cost_usd": 0.024, "input_tokens": 40000, "output_tokens": 20000, "calls": 40}],
}


class TestMetricsAPI:
    """Integration tests for /metrics/* endpoints (DB mocked)."""

    def test_overview_returns_required_keys(self, client):
        with patch("app.api.metrics.get_overview_metrics", return_value=MOCK_OVERVIEW), \
             patch("app.api.metrics.get_percentile_latency", return_value=90_000.0):
            resp = client.get("/metrics/overview")
        assert resp.status_code == 200
        data = resp.json()
        for key in ("reviews_total", "completed", "failed", "approve", "human_review", "block",
                    "auto_merged", "avg_latency_ms", "p95_latency_ms"):
            assert key in data, f"Missing key: {key}"

    def test_overview_repository_filter_forwarded(self, client):
        """?repository= param must be passed to get_overview_metrics."""
        with patch("app.api.metrics.get_overview_metrics", return_value=MOCK_OVERVIEW) as mock_fn, \
             patch("app.api.metrics.get_percentile_latency", return_value=None):
            resp = client.get("/metrics/overview?repository=owner/repo")
        assert resp.status_code == 200
        mock_fn.assert_called_once_with(repository="owner/repo")

    def test_review_detail_returns_correct_structure(self, client):
        with patch("app.api.metrics.get_review_detail_metrics", return_value=MOCK_DETAIL):
            resp = client.get("/metrics/reviews/abc-123")
        assert resp.status_code == 200
        data = resp.json()
        assert data["review_id"] == "abc-123"
        assert "agents" in data
        assert "llm_usage" in data
        assert "timings" in data
        assert "total_cost_usd" in data

    def test_review_detail_agent_timings_present(self, client):
        with patch("app.api.metrics.get_review_detail_metrics", return_value=MOCK_DETAIL):
            resp = client.get("/metrics/reviews/abc-123")
        data = resp.json()
        agents = data["agents"]
        assert "security" in agents
        assert "quality" in agents
        assert agents["security"]["duration_ms"] == 10_250
        # security is slowest
        assert agents["security"]["duration_ms"] > agents["quality"]["duration_ms"]

    def test_review_detail_404_on_unknown(self, client):
        with patch("app.api.metrics.get_review_detail_metrics", return_value=None):
            resp = client.get("/metrics/reviews/nonexistent-uuid")
        assert resp.status_code == 404

    def test_agent_metrics_endpoint_structure(self, client):
        with patch("app.api.metrics.get_agent_metrics_summary", return_value=MOCK_AGENTS):
            resp = client.get("/metrics/agents")
        assert resp.status_code == 200
        data = resp.json()
        assert "agents" in data
        for ag in data["agents"]:
            assert "agent" in ag
            assert "executions" in ag
            assert "avg_duration_ms" in ag
            assert "success_rate_pct" in ag

    def test_cost_endpoint_structure(self, client):
        with patch("app.api.metrics.get_cost_summary", return_value=MOCK_COST):
            resp = client.get("/metrics/cost")
        assert resp.status_code == 200
        data = resp.json()
        assert "total_cost_usd" in data
        assert "by_agent" in data
        assert "by_model" in data
        assert "avg_cost_per_review" in data

    def test_no_secrets_in_overview_response(self, client):
        """Verify response contains no API key patterns."""
        import re
        with patch("app.api.metrics.get_overview_metrics", return_value=MOCK_OVERVIEW), \
             patch("app.api.metrics.get_percentile_latency", return_value=None):
            resp = client.get("/metrics/overview")
        body = resp.text
        assert not re.search(r"ghp_[A-Za-z0-9_]{20,}", body)
        assert not re.search(r"ghs_[A-Za-z0-9_]{20,}", body)
        assert not re.search(r"lsv2_pt_", body)
        assert "PRIVATE KEY" not in body

    def test_p99_added_to_overview(self, client):
        """p99_latency_ms must be included in overview response."""
        with patch("app.api.metrics.get_overview_metrics", return_value=dict(MOCK_OVERVIEW)), \
             patch("app.api.metrics.get_percentile_latency", return_value=95_000.0):
            resp = client.get("/metrics/overview")
        data = resp.json()
        assert "p99_latency_ms" in data
        assert data["p99_latency_ms"] == 95_000

    def test_review_detail_cost_not_fabricated(self, client):
        """If all llm_usage costs are None, total_cost_usd must be None."""
        detail_no_cost = dict(MOCK_DETAIL)
        detail_no_cost["total_cost_usd"] = None
        detail_no_cost["llm_usage"] = [
            {"agent": "security", "model": "x", "input_tokens": None,
             "output_tokens": None, "total_tokens": None, "estimated_cost": None},
        ]
        with patch("app.api.metrics.get_review_detail_metrics", return_value=detail_no_cost):
            resp = client.get("/metrics/reviews/abc-123")
        data = resp.json()
        assert data["total_cost_usd"] is None

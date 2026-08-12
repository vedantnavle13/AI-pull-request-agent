"""
Database schema initialization and migrations.

This module owns the runtime PostgreSQL schema for the AI Pull Request
Review Agent.

The schema is intentionally idempotent:
- safe to run on a brand-new database
- safe to run repeatedly on an existing database
- does not drop existing data
- safe to call during worker startup

Covered phases:
- Phase 11: GitHub published comments
- Phase 12: review lifecycle, retries, LLM usage, metrics
- Phase 13: auto-merge audit trail
- Phase 14: agent metrics, error metrics, observability
"""

import logging

from app.database.postgres import get_connection


logger = logging.getLogger(__name__)


def ensure_schema() -> None:
    """
    Initialize/update the application database schema.

    This function is idempotent and safe to execute repeatedly.

    It creates:
        - pgcrypto extension
        - reviews
        - published_comments
        - review_runs
        - llm_usage
        - review_metrics
        - auto_merges
        - agent_metrics
        - error_metrics

    It also creates the indexes required by the application.
    """

    conn = get_connection()

    try:
        with conn.cursor() as cursor:

            # ---------------------------------------------------------
            # PostgreSQL extensions
            # ---------------------------------------------------------
            # Required for gen_random_uuid().
            cursor.execute(
                """
                CREATE EXTENSION IF NOT EXISTS pgcrypto;
                """
            )

            # ---------------------------------------------------------
            # Core reviews table
            # ---------------------------------------------------------
            # This table previously existed only in schema.sql.
            # Since schema.sql is not executed by the application,
            # it MUST also be created here for a fresh database.
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS reviews (
                    id              SERIAL PRIMARY KEY,
                    repository      VARCHAR(255) NOT NULL,
                    pr_number       INTEGER NOT NULL,
                    commit_sha      VARCHAR(64) NOT NULL,
                    decision        VARCHAR(50) NOT NULL,
                    status          VARCHAR(50) NOT NULL DEFAULT 'QUEUED',
                    findings        JSONB,
                    error_message   TEXT,
                    attempts        INTEGER NOT NULL DEFAULT 0,
                    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    started_at      TIMESTAMP,
                    completed_at    TIMESTAMP,
                    github_review_id BIGINT,

                    UNIQUE(repository, pr_number, commit_sha)
                );
                """
            )

            # ---------------------------------------------------------
            # Phase 11 — Published GitHub comments
            # ---------------------------------------------------------
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS published_comments (
                    id              SERIAL PRIMARY KEY,
                    finding_hash    TEXT NOT NULL UNIQUE,
                    repository      TEXT NOT NULL,
                    pr_number       INTEGER NOT NULL,
                    commit_sha      TEXT NOT NULL,
                    github_id       BIGINT,
                    created_at      TIMESTAMPTZ NOT NULL
                                    DEFAULT CURRENT_TIMESTAMP
                );
                """
            )

            # ---------------------------------------------------------
            # Phase 12 — Review lifecycle / idempotency
            # ---------------------------------------------------------
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS review_runs (
                    id              UUID PRIMARY KEY,
                    installation_id BIGINT NOT NULL,
                    owner           TEXT NOT NULL,
                    repo            TEXT NOT NULL,
                    pr_number       INTEGER NOT NULL,
                    commit_sha      TEXT NOT NULL,
                    status          TEXT NOT NULL,
                    attempt_count   INTEGER NOT NULL DEFAULT 0,
                    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    started_at      TIMESTAMPTZ,
                    completed_at    TIMESTAMPTZ,
                    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    error_type      TEXT,
                    error_message   TEXT,

                    UNIQUE (
                        installation_id,
                        owner,
                        repo,
                        pr_number,
                        commit_sha
                    )
                );
                """
            )

            # ---------------------------------------------------------
            # Phase 14 — LLM usage / economics
            # ---------------------------------------------------------
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS llm_usage (
                    id              UUID PRIMARY KEY,
                    review_id       UUID NOT NULL,
                    agent           TEXT NOT NULL,
                    model           TEXT NOT NULL,
                    input_tokens    INTEGER,
                    output_tokens   INTEGER,
                    total_tokens    INTEGER,
                    estimated_cost  NUMERIC,
                    created_at      TIMESTAMPTZ DEFAULT NOW()
                );
                """
            )

            # ---------------------------------------------------------
            # Phase 14 — Review-level timing metrics
            # ---------------------------------------------------------
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS review_metrics (
                    id                      UUID PRIMARY KEY,
                    review_id               UUID NOT NULL UNIQUE,

                    total_duration_ms      INTEGER,
                    queue_wait_ms          INTEGER,
                    checkout_duration_ms   INTEGER,
                    context_build_ms      INTEGER,

                    agent_duration_ms     INTEGER,
                    validation_duration_ms INTEGER,
                    test_duration_ms      INTEGER,
                    publishing_duration_ms INTEGER,
                    auto_merge_ms         INTEGER,

                    final_decision         TEXT,
                    final_status           TEXT,

                    created_at             TIMESTAMPTZ DEFAULT NOW()
                );
                """
            )

            # ---------------------------------------------------------
            # Phase 13 — Auto-merge audit trail
            # ---------------------------------------------------------
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS auto_merges (
                    id                  UUID PRIMARY KEY
                                        DEFAULT gen_random_uuid(),

                    review_id           UUID NOT NULL UNIQUE,
                    repository         TEXT NOT NULL,
                    pr_number          INTEGER NOT NULL,

                    reviewed_sha       TEXT NOT NULL,
                    current_sha        TEXT,

                    decision            TEXT NOT NULL,
                    merge_status       TEXT NOT NULL
                                        DEFAULT 'NOT_ELIGIBLE',

                    merge_method       TEXT,
                    checks_status      TEXT,

                    merge_attempts     INTEGER NOT NULL DEFAULT 0,

                    merge_started_at   TIMESTAMPTZ,
                    merge_completed_at TIMESTAMPTZ,

                    merge_sha          TEXT,
                    merge_commit_sha   TEXT,

                    error               TEXT,

                    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                """
            )

            # ---------------------------------------------------------
            # Phase 14 — Per-agent metrics
            # ---------------------------------------------------------
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS agent_metrics (
                    id              UUID PRIMARY KEY
                                    DEFAULT gen_random_uuid(),

                    review_id       UUID NOT NULL,
                    agent_name      TEXT NOT NULL,

                    started_at      TIMESTAMPTZ,
                    completed_at    TIMESTAMPTZ,

                    duration_ms     INTEGER,

                    success         BOOLEAN,
                    finding_count   INTEGER,

                    error_type      TEXT,
                    error_message   TEXT,

                    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                """
            )

            # ---------------------------------------------------------
            # Phase 14 — Error metrics
            # ---------------------------------------------------------
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS error_metrics (
                    id              UUID PRIMARY KEY
                                    DEFAULT gen_random_uuid(),

                    review_id       UUID,

                    stage           TEXT NOT NULL,
                    error_category  TEXT NOT NULL,

                    error_type      TEXT,
                    error_message   TEXT,

                    retryable       BOOLEAN,
                    attempt         INTEGER,

                    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                """
            )

            # ---------------------------------------------------------
            # Indexes — published comments
            # ---------------------------------------------------------
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS
                    idx_published_comments_hash
                ON published_comments (finding_hash);
                """
            )

            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS
                    idx_published_comments_pr
                ON published_comments (
                    repository,
                    pr_number,
                    commit_sha
                );
                """
            )

            # ---------------------------------------------------------
            # Indexes — reviews
            # ---------------------------------------------------------
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS
                    idx_reviews_repository
                ON reviews (repository);
                """
            )

            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS
                    idx_reviews_created_at
                ON reviews (created_at);
                """
            )

            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS
                    idx_reviews_status
                ON reviews (status);
                """
            )

            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS
                    idx_reviews_decision
                ON reviews (decision);
                """
            )

            # ---------------------------------------------------------
            # Indexes — review runs
            # ---------------------------------------------------------
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS
                    idx_review_runs_lookup
                ON review_runs (
                    owner,
                    repo,
                    pr_number,
                    commit_sha
                );
                """
            )

            # ---------------------------------------------------------
            # Indexes — LLM usage
            # ---------------------------------------------------------
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS
                    idx_llm_usage_review
                ON llm_usage (review_id);
                """
            )

            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS
                    idx_llm_usage_agent
                ON llm_usage (agent);
                """
            )

            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS
                    idx_llm_usage_created_at
                ON llm_usage (created_at);
                """
            )

            # ---------------------------------------------------------
            # Indexes — review metrics
            # ---------------------------------------------------------
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS
                    idx_review_metrics_created
                ON review_metrics (created_at);
                """
            )

            # ---------------------------------------------------------
            # Indexes — auto merges
            # ---------------------------------------------------------
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS
                    idx_auto_merges_review_id
                ON auto_merges (review_id);
                """
            )

            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS
                    idx_auto_merges_pr
                ON auto_merges (repository, pr_number);
                """
            )

            # ---------------------------------------------------------
            # Indexes — agent metrics
            # ---------------------------------------------------------
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS
                    idx_agent_metrics_review_id
                ON agent_metrics (review_id);
                """
            )

            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS
                    idx_agent_metrics_agent
                ON agent_metrics (agent_name);
                """
            )

            # ---------------------------------------------------------
            # Indexes — error metrics
            # ---------------------------------------------------------
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS
                    idx_error_metrics_review_id
                ON error_metrics (review_id);
                """
            )

            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS
                    idx_error_metrics_category
                ON error_metrics (error_category);
                """
            )

        # -------------------------------------------------------------
        # Commit everything atomically
        # -------------------------------------------------------------
        conn.commit()

        logger.info(
            "Database schema initialized successfully "
            "(Phases 11-14)."
        )

    except Exception as exc:
        conn.rollback()

        logger.exception(
            "Database schema initialization failed: %s",
            exc,
        )

        raise

    finally:
        conn.close()
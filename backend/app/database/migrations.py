"""
Phase 11 & Phase 12 — Database schema migrations.

Applies CREATE TABLE IF NOT EXISTS for any tables added in Phase 11 and Phase 12.
Called once at worker startup — idempotent and safe to run repeatedly.
"""

import logging

from app.database.postgres import get_connection

logger = logging.getLogger(__name__)


def ensure_schema() -> None:
    """
    Create Phase 11 & Phase 12 tables if they do not already exist.

    Tables created:
        published_comments  — tracks inline GitHub review comments posted
        review_runs         — review lifecycle state machine (UUID primary key)
        llm_usage           — per-agent token usage & estimated cost tracking
        review_metrics      — duration breakdowns per review stage
    """

    conn = get_connection()

    try:
        with conn.cursor() as cursor:

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS published_comments (
                    id              SERIAL PRIMARY KEY,
                    finding_hash    TEXT        NOT NULL UNIQUE,
                    repository      TEXT        NOT NULL,
                    pr_number       INTEGER     NOT NULL,
                    commit_sha      TEXT        NOT NULL,
                    github_id       BIGINT,
                    created_at      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE INDEX IF NOT EXISTS
                    idx_published_comments_hash
                ON published_comments (finding_hash);

                CREATE INDEX IF NOT EXISTS
                    idx_published_comments_pr
                ON published_comments (repository, pr_number, commit_sha);

                CREATE TABLE IF NOT EXISTS review_runs (
                    id              UUID PRIMARY KEY,
                    installation_id BIGINT      NOT NULL,
                    owner           TEXT        NOT NULL,
                    repo            TEXT        NOT NULL,
                    pr_number       INTEGER     NOT NULL,
                    commit_sha      TEXT        NOT NULL,
                    status          TEXT        NOT NULL,
                    attempt_count   INTEGER     NOT NULL DEFAULT 0,
                    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    started_at      TIMESTAMPTZ,
                    completed_at    TIMESTAMPTZ,
                    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    error_type      TEXT,
                    error_message   TEXT,
                    UNIQUE (installation_id, owner, repo, pr_number, commit_sha)
                );

                CREATE INDEX IF NOT EXISTS
                    idx_review_runs_lookup
                ON review_runs (owner, repo, pr_number, commit_sha);

                CREATE TABLE IF NOT EXISTS llm_usage (
                    id              UUID PRIMARY KEY,
                    review_id       UUID        NOT NULL,
                    agent           TEXT        NOT NULL,
                    model           TEXT        NOT NULL,
                    input_tokens    INTEGER,
                    output_tokens   INTEGER,
                    total_tokens    INTEGER,
                    estimated_cost  NUMERIC,
                    created_at      TIMESTAMPTZ DEFAULT NOW()
                );

                CREATE INDEX IF NOT EXISTS
                    idx_llm_usage_review
                ON llm_usage (review_id);

                CREATE TABLE IF NOT EXISTS review_metrics (
                    id                      UUID PRIMARY KEY,
                    review_id               UUID        NOT NULL UNIQUE,
                    total_duration_ms       INTEGER,
                    queue_wait_ms           INTEGER,
                    checkout_duration_ms    INTEGER,
                    agent_duration_ms       INTEGER,
                    validation_duration_ms  INTEGER,
                    test_duration_ms        INTEGER,
                    publishing_duration_ms  INTEGER,
                    created_at              TIMESTAMPTZ DEFAULT NOW()
                );
                """
            )

        conn.commit()
        logger.info("Phase 11/12 schema is up to date.")

    except Exception as exc:
        conn.rollback()
        logger.error("Schema migration failed: %s", exc)
        raise

    finally:
        conn.close()

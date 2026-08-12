"""
Phase 11, 12 & 13 — Database schema migrations.

Applies CREATE TABLE IF NOT EXISTS for all tables added in Phase 11, 12, and 13.
Called once at worker startup — idempotent and safe to run repeatedly.
"""

import logging

from app.database.postgres import get_connection

logger = logging.getLogger(__name__)


def ensure_schema() -> None:
    """
    Create Phase 11, 12, and 13 tables if they do not already exist.

    Tables created:
        published_comments  — tracks inline GitHub review comments posted
        review_runs         — review lifecycle state machine (UUID primary key)
        llm_usage           — per-agent token usage & estimated cost tracking
        review_metrics      — duration breakdowns per review stage
        auto_merges         — auto-merge decision audit trail (Phase 13)
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

                CREATE TABLE IF NOT EXISTS auto_merges (
                    id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
                    review_id           UUID        NOT NULL UNIQUE,
                    repository          TEXT        NOT NULL,
                    pr_number           INTEGER     NOT NULL,
                    reviewed_sha        TEXT        NOT NULL,
                    current_sha         TEXT,
                    decision            TEXT        NOT NULL,
                    merge_status        TEXT        NOT NULL DEFAULT 'NOT_ELIGIBLE',
                    merge_method        TEXT,
                    checks_status       TEXT,
                    merge_attempts      INTEGER     NOT NULL DEFAULT 0,
                    merge_started_at    TIMESTAMPTZ,
                    merge_completed_at  TIMESTAMPTZ,
                    merge_sha           TEXT,
                    merge_commit_sha    TEXT,
                    error               TEXT,
                    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );

                CREATE INDEX IF NOT EXISTS idx_auto_merges_review_id ON auto_merges (review_id);
                CREATE INDEX IF NOT EXISTS idx_auto_merges_pr ON auto_merges (repository, pr_number);

                -- Phase 14: per-agent timing and result metrics
                CREATE TABLE IF NOT EXISTS agent_metrics (
                    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
                    review_id       UUID        NOT NULL,
                    agent_name      TEXT        NOT NULL,
                    started_at      TIMESTAMPTZ,
                    completed_at    TIMESTAMPTZ,
                    duration_ms     INTEGER,
                    success         BOOLEAN,
                    finding_count   INTEGER,
                    error_type      TEXT,
                    error_message   TEXT,
                    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );

                CREATE INDEX IF NOT EXISTS idx_agent_metrics_review_id ON agent_metrics (review_id);
                CREATE INDEX IF NOT EXISTS idx_agent_metrics_agent     ON agent_metrics (agent_name);

                -- Phase 14: error categorization for failure analysis
                CREATE TABLE IF NOT EXISTS error_metrics (
                    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
                    review_id       UUID,
                    stage           TEXT        NOT NULL,
                    error_category  TEXT        NOT NULL,
                    error_type      TEXT,
                    error_message   TEXT,
                    retryable       BOOLEAN,
                    attempt         INTEGER,
                    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );

                CREATE INDEX IF NOT EXISTS idx_error_metrics_review_id ON error_metrics (review_id);
                CREATE INDEX IF NOT EXISTS idx_error_metrics_category  ON error_metrics (error_category);

                -- Phase 14: indexes for metrics queries
                CREATE INDEX IF NOT EXISTS idx_reviews_repository       ON reviews (repository);
                CREATE INDEX IF NOT EXISTS idx_reviews_created_at       ON reviews (created_at);
                CREATE INDEX IF NOT EXISTS idx_reviews_status           ON reviews (status);
                CREATE INDEX IF NOT EXISTS idx_reviews_decision         ON reviews (decision);
                CREATE INDEX IF NOT EXISTS idx_review_metrics_created   ON review_metrics (created_at);
                CREATE INDEX IF NOT EXISTS idx_llm_usage_agent          ON llm_usage (agent);
                CREATE INDEX IF NOT EXISTS idx_llm_usage_created_at     ON llm_usage (created_at);
                """
            )

        # Phase 14: extend review_metrics with new columns (ALTER TABLE is idempotent via IF NOT EXISTS)
        with conn.cursor() as cursor:
            for col_ddl in [
                "ALTER TABLE review_metrics ADD COLUMN IF NOT EXISTS queue_wait_ms     INTEGER",
                "ALTER TABLE review_metrics ADD COLUMN IF NOT EXISTS context_build_ms  INTEGER",
                "ALTER TABLE review_metrics ADD COLUMN IF NOT EXISTS auto_merge_ms     INTEGER",
                "ALTER TABLE review_metrics ADD COLUMN IF NOT EXISTS final_decision     TEXT",
                "ALTER TABLE review_metrics ADD COLUMN IF NOT EXISTS final_status       TEXT",
            ]:
                cursor.execute(col_ddl)

        conn.commit()
        logger.info("Phase 11/12/13/14 schema is up to date.")

    except Exception as exc:
        conn.rollback()
        logger.error("Schema migration failed: %s", exc)
        raise

    finally:
        conn.close()

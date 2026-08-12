CREATE TABLE IF NOT EXISTS reviews (
    id SERIAL PRIMARY KEY,
    repository VARCHAR(255) NOT NULL,
    pr_number INTEGER NOT NULL,
    commit_sha VARCHAR(64) NOT NULL,
    decision VARCHAR(50) NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'QUEUED',
    findings JSONB,
    error_message TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    github_review_id BIGINT,
    UNIQUE(repository, pr_number, commit_sha)
);

CREATE TABLE IF NOT EXISTS review_runs (
    id UUID PRIMARY KEY,
    installation_id BIGINT NOT NULL,
    owner TEXT NOT NULL,
    repo TEXT NOT NULL,
    pr_number INTEGER NOT NULL,
    commit_sha TEXT NOT NULL,
    status TEXT NOT NULL,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    error_type TEXT,
    error_message TEXT,
    UNIQUE (installation_id, owner, repo, pr_number, commit_sha)
);

CREATE TABLE IF NOT EXISTS llm_usage (
    id UUID PRIMARY KEY,
    review_id UUID NOT NULL,
    agent TEXT NOT NULL,
    model TEXT NOT NULL,
    input_tokens INTEGER,
    output_tokens INTEGER,
    total_tokens INTEGER,
    estimated_cost NUMERIC,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS review_metrics (
    id UUID PRIMARY KEY,
    review_id UUID NOT NULL UNIQUE,
    total_duration_ms INTEGER,
    queue_wait_ms INTEGER,
    checkout_duration_ms INTEGER,
    agent_duration_ms INTEGER,
    validation_duration_ms INTEGER,
    test_duration_ms INTEGER,
    publishing_duration_ms INTEGER,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Phase 13: auto-merge audit trail
CREATE TABLE IF NOT EXISTS auto_merges (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
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
CREATE INDEX IF NOT EXISTS idx_agent_metrics_agent ON agent_metrics (agent_name);

-- Phase 14: structured error categorization for failure analysis
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
CREATE INDEX IF NOT EXISTS idx_error_metrics_category ON error_metrics (error_category);

-- Phase 14: useful indexes on core tables for metrics queries
CREATE INDEX IF NOT EXISTS idx_reviews_repository ON reviews (repository);
CREATE INDEX IF NOT EXISTS idx_reviews_created_at ON reviews (created_at);
CREATE INDEX IF NOT EXISTS idx_reviews_status ON reviews (status);
CREATE INDEX IF NOT EXISTS idx_reviews_decision ON reviews (decision);
CREATE INDEX IF NOT EXISTS idx_review_metrics_created_at ON review_metrics (created_at);
CREATE INDEX IF NOT EXISTS idx_llm_usage_agent ON llm_usage (agent);
CREATE INDEX IF NOT EXISTS idx_llm_usage_created_at ON llm_usage (created_at);
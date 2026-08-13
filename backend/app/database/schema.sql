-- ============================================================
-- Core reviews table (Phase 1 / legacy)
-- decision is nullable: set only after AI completes.
-- ============================================================
CREATE TABLE IF NOT EXISTS reviews (
    id SERIAL PRIMARY KEY,
    repository VARCHAR(255) NOT NULL,
    pr_number INTEGER NOT NULL,
    commit_sha VARCHAR(64) NOT NULL,
    decision VARCHAR(50),
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


CREATE TABLE IF NOT EXISTS webhook_deliveries (
    id SERIAL PRIMARY KEY,
    delivery_id VARCHAR(255) NOT NULL UNIQUE,
    event_type VARCHAR(100),
    action VARCHAR(100),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_webhook_deliveries_created_at
ON webhook_deliveries (created_at);

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

-- ============================================================
-- Phase 3: Multi-user / SaaS tables
-- ============================================================

-- Application users identified via GitHub OAuth
CREATE TABLE IF NOT EXISTS users (
    id                UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    github_user_id    BIGINT      NOT NULL UNIQUE,
    github_username   TEXT        NOT NULL,
    github_avatar_url TEXT,
    email             TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_users_github_user_id ON users (github_user_id);

-- GitHub App installations linked to users
-- installation_id is the numeric ID that GitHub sends in webhooks.
CREATE TABLE IF NOT EXISTS github_installations (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    installation_id BIGINT      NOT NULL UNIQUE,
    account_id      BIGINT      NOT NULL,
    account_login   TEXT        NOT NULL,
    account_type    TEXT        NOT NULL,       -- 'User' or 'Organization'
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_github_installations_user_id        ON github_installations (user_id);
CREATE INDEX IF NOT EXISTS idx_github_installations_installation_id ON github_installations (installation_id);

-- Repositories accessible to each GitHub App installation
CREATE TABLE IF NOT EXISTS repositories (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    installation_id UUID        NOT NULL REFERENCES github_installations(id) ON DELETE CASCADE,
    github_repo_id  BIGINT      NOT NULL,
    owner           TEXT        NOT NULL,
    name            TEXT        NOT NULL,
    full_name       TEXT        NOT NULL,
    private         BOOLEAN     NOT NULL DEFAULT FALSE,
    default_branch  TEXT        NOT NULL DEFAULT 'main',
    active          BOOLEAN     NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (installation_id, github_repo_id)
);

CREATE INDEX IF NOT EXISTS idx_repositories_installation_id ON repositories (installation_id);
CREATE INDEX IF NOT EXISTS idx_repositories_full_name       ON repositories (full_name);
CREATE INDEX IF NOT EXISTS idx_repositories_github_repo_id  ON repositories (github_repo_id);
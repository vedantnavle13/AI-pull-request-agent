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
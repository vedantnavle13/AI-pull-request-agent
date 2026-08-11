CREATE TABLE IF NOT EXISTS reviews (
    id SERIAL PRIMARY KEY,

    repository VARCHAR(255) NOT NULL,

    pr_number INTEGER NOT NULL,

    commit_sha VARCHAR(64) NOT NULL,

    decision VARCHAR(50) NOT NULL,

    status VARCHAR(50) NOT NULL DEFAULT 'QUEUED',

    findings JSONB,

    error_message TEXT,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    started_at TIMESTAMP,

    completed_at TIMESTAMP,

    UNIQUE(repository, pr_number, commit_sha)
);
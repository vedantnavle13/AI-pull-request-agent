import json

from psycopg2.extras import Json
# pyrefly: ignore [missing-import]
from psycopg.types.json import Json

# pyrefly: ignore [missing-import]
from psycopg.types.json import Jsonb
from app.database.postgres import get_connection


def register_webhook_delivery(
    delivery_id: str,
    event_type: str,
    action: str | None,
) -> bool:
    """
    Persist a GitHub webhook delivery ID.

    Returns:
        True  -> this delivery is new
        False -> this delivery was already processed
    """

    conn = get_connection()

    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO webhook_deliveries (
                    delivery_id,
                    event_type,
                    action
                )
                VALUES (%s, %s, %s)
                ON CONFLICT (delivery_id)
                DO NOTHING
                """,
                (
                    delivery_id,
                    event_type,
                    action,
                ),
            )

            created = cursor.rowcount == 1

        conn.commit()

        return created

    finally:
        conn.close()


def create_review(
    repository: str,
    pr_number: int,
    commit_sha: str,
) -> bool:
    """
    Create a review record.

    Returns:
        True  -> new review created
        False -> review already exists
    """

    conn = get_connection()

    try:
        with conn.cursor() as cursor:
            cursor.execute(
    """
    INSERT INTO reviews (
        repository,
        pr_number,
        commit_sha,
        status,
        decision
    )
    VALUES (%s, %s, %s, 'QUEUED', 'PENDING')
    ON CONFLICT (
        repository,
        pr_number,
        commit_sha
    )
    DO NOTHING
    """,
    (
        repository,
        pr_number,
        commit_sha,
    ),
)

            created = cursor.rowcount == 1

        conn.commit()

        return created

    finally:
        conn.close()


def claim_review(
    repository: str,
    pr_number: int,
    commit_sha: str,
) -> bool:
    """
    Called by the WEBHOOK HANDLER to atomically register a new
    (repository, pr_number, commit_sha) tuple.

    Inserts a row with status='QUEUED' and returns True.
    If this exact triple already exists (any status), returns False —
    the webhook delivery is a duplicate and the job should not be
    re-queued.

    Identity is: repository + pr_number + commit_sha.
    A new commit SHA on the same PR is always a new review.
    """

    conn = get_connection()

    try:

        with conn.cursor() as cursor:

            cursor.execute(
                """
                INSERT INTO reviews (
                    repository,
                    pr_number,
                    commit_sha,
                    status
                )
                VALUES (
                    %s,
                    %s,
                    %s,
                    'QUEUED'
                )
                ON CONFLICT (
                    repository,
                    pr_number,
                    commit_sha
                )
                DO NOTHING
                RETURNING id
                """,
                (
                    repository,
                    pr_number,
                    commit_sha,
                ),
            )

            row = cursor.fetchone()

        conn.commit()

        return row is not None

    finally:

        conn.close()


# How long a PROCESSING review is considered "stale" before a retry is allowed.
_STALE_PROCESSING_MINUTES = 10


def start_review(
    repository: str,
    pr_number: int,
    commit_sha: str,
) -> bool:
    """
    Called by the WORKER to atomically claim a review for processing.

    This implements the worker-side state machine:

        QUEUED              → PROCESSING  ✅  (normal path)
        FAILED              → PROCESSING  ✅  (retry)
        PROCESSING + stale  → PROCESSING  ✅  (retry hung worker)
        PROCESSING + fresh  → False       🚫  (another worker has it)
        COMPLETED           → False       🚫  (already done)

    Returns:
        True  — this worker has claimed the review and should proceed.
        False — review is already being processed or is complete; skip.

    This is separate from claim_review() (the webhook-side INSERT) because
    the webhook always inserts QUEUED first. If the worker also tries to
    INSERT it gets ON CONFLICT → DO NOTHING → no row returned → incorrectly
    skips a genuine new review.

    Atomicity: the UPDATE ... WHERE status IN (...) RETURNING id is a
    single atomic SQL operation. Even if two ARQ workers execute it
    concurrently for the same row, only one UPDATE will match and return
    the row — the other will see 0 rows updated.
    """

    conn = get_connection()

    try:
        with conn.cursor() as cursor:

            # ----------------------------------------------------------------
            # 1. Print diagnostics before deciding.
            # ----------------------------------------------------------------
            cursor.execute(
                """
                SELECT id, status, started_at, completed_at
                FROM   reviews
                WHERE  repository = %s
                  AND  pr_number  = %s
                  AND  commit_sha = %s
                """,
                (repository, pr_number, commit_sha),
            )
            existing = cursor.fetchone()
            print(
                f"[start_review] repository={repository!r} "
                f"pr={pr_number} sha={commit_sha[:8]}"
            )
            if existing:
                print(
                    f"[start_review] existing row: id={existing[0]} "
                    f"status={existing[1]} "
                    f"started_at={existing[2]} "
                    f"completed_at={existing[3]}"
                )
            else:
                print("[start_review] no existing row for this SHA")

            # ----------------------------------------------------------------
            # 2. Atomically transition eligible states → PROCESSING.
            # ----------------------------------------------------------------
            cursor.execute(
                """
                UPDATE reviews
                SET
                    status     = 'PROCESSING',
                    started_at = CURRENT_TIMESTAMP,
                    attempts   = attempts + 1
                WHERE  repository = %s
                  AND  pr_number  = %s
                  AND  commit_sha = %s
                  AND  (
                         status = 'QUEUED'
                      OR status = 'FAILED'
                      OR (
                             status     = 'PROCESSING'
                         AND started_at < NOW() - INTERVAL '%s minutes'
                      )
                  )
                RETURNING id, status
                """,
                (repository, pr_number, commit_sha, _STALE_PROCESSING_MINUTES),
            )

            row = cursor.fetchone()

        conn.commit()

        if row:
            print(f"[start_review] → CLAIMED (id={row[0]})")
        else:
            # Re-fetch to print why we skipped.
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT status, started_at FROM reviews "
                    "WHERE repository=%s AND pr_number=%s AND commit_sha=%s",
                    (repository, pr_number, commit_sha),
                )
                skip_row = cursor.fetchone()
            reason = f"status={skip_row[0]}" if skip_row else "row missing"
            print(f"[start_review] → SKIPPED ({reason})")

        return row is not None

    finally:

        conn.close()


def update_review_status(
    repository: str,
    pr_number: int,
    commit_sha: str,
    status: str,
):

    """
    Update the status of an existing review.
    """

    conn = get_connection()

    try:
        with conn.cursor() as cursor:

            if status == "PROCESSING":
                cursor.execute(
                    """
                    UPDATE reviews
                    SET
                        status = %s,
                        started_at = CURRENT_TIMESTAMP
                    WHERE repository = %s
                      AND pr_number = %s
                      AND commit_sha = %s
                    """,
                    (
                        status,
                        repository,
                        pr_number,
                        commit_sha,
                    ),
                )

            else:
                cursor.execute(
                    """
                    UPDATE reviews
                    SET
                        status = %s
                    WHERE repository = %s
                      AND pr_number = %s
                      AND commit_sha = %s
                    """,
                    (
                        status,
                        repository,
                        pr_number,
                        commit_sha,
                    ),
                )

        conn.commit()

    finally:
        conn.close()


def complete_review(
    repository,
    pr_number,
    commit_sha,
    decision,
    findings,
    github_review_id=None,
):
    """
    Mark a review as completed and save the AI result.
    """

    conn = get_connection()

    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE reviews
                SET
                    status = 'COMPLETED',
                    decision = %s,
                    findings = %s,
                    completed_at = CURRENT_TIMESTAMP
                WHERE repository = %s
                  AND pr_number = %s
                  AND commit_sha = %s
                """,
                (
                    decision,
                    Jsonb(findings),
                    repository,
                    pr_number,
                    commit_sha,
                ),
            )

        conn.commit()

    finally:
        conn.close()


def fail_review(
    repository: str,
    pr_number: int,
    commit_sha: str,
    error_message: str,
):
    conn = get_connection()

    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE reviews
                SET
                    status = 'FAILED',
                    error_message = %s,
                    completed_at = CURRENT_TIMESTAMP
                WHERE repository = %s
                  AND pr_number = %s
                  AND commit_sha = %s
                """,
                (
                    error_message,
                    repository,
                    pr_number,
                    commit_sha,
                ),
            )

        conn.commit()

    finally:
        conn.close()


def requeue_review(
    repository: str,
    pr_number: int,
    commit_sha: str,
):
    conn = get_connection()

    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE reviews
                SET
                    status = 'QUEUED',
                    error_message = NULL
                WHERE repository = %s
                  AND pr_number = %s
                  AND commit_sha = %s
                """,
                (
                    repository,
                    pr_number,
                    commit_sha,
                ),
            )

        conn.commit()

    finally:
        conn.close()        


def get_review(
    repository: str,
    pr_number: int,
    commit_sha: str,
):
    conn = get_connection()

    try:
        with conn.cursor() as cursor:

            cursor.execute(
                """
                SELECT
                    repository,
                    pr_number,
                    commit_sha,
                    decision,
                    status,
                    findings,
                    error_message,
                    attempts,
                    created_at,
                    started_at,
                    completed_at
                FROM reviews
                WHERE repository = %s
                  AND pr_number = %s
                  AND commit_sha = %s
                """,
                (
                    repository,
                    pr_number,
                    commit_sha,
                ),
            )

            row = cursor.fetchone()

            if not row:
                return None

            return {
                "repository": row[0],
                "pr_number": row[1],
                "commit_sha": row[2],
                "decision": row[3],
                "status": row[4],
                "findings": row[5],
                "error_message": row[6],
                "attempts": row[7],
                "created_at": row[8],
                "started_at": row[9],
                "completed_at": row[10],
            }

    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Phase 11 — Published comments idempotency
# ---------------------------------------------------------------------------

def is_comment_published(finding_hash: str) -> bool:
    """
    Return True if a finding with this hash has already been posted
    as an inline GitHub review comment.
    """

    conn = get_connection()

    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT 1
                FROM published_comments
                WHERE finding_hash = %s
                LIMIT 1
                """,
                (finding_hash,),
            )
            return cursor.fetchone() is not None

    finally:
        conn.close()


def record_published_comment(
    finding_hash: str,
    repository: str,
    pr_number: int,
    commit_sha: str,
    github_id: int | None = None,
) -> None:
    """
    Record that a finding has been successfully posted as an inline
    GitHub review comment.  Silently ignores duplicate inserts.
    """

    conn = get_connection()

    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO published_comments (
                    finding_hash,
                    repository,
                    pr_number,
                    commit_sha,
                    github_id
                )
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (finding_hash)
                DO NOTHING
                """,
                (
                    finding_hash,
                    repository,
                    pr_number,
                    commit_sha,
                    github_id,
                ),
            )

        conn.commit()

    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Phase 12 — Lifecycle State Machine & Metrics Repository
# ---------------------------------------------------------------------------

from dataclasses import dataclass
import uuid
from datetime import datetime, timezone
from app.config import REVIEW_STALE_TIMEOUT_SECONDS


@dataclass
class ReviewClaim:
    claimed: bool
    review_id: str | None = None
    reason: str | None = None


def claim_review_run(
    installation_id: int,
    owner: str,
    repo: str,
    pr_number: int,
    commit_sha: str,
) -> ReviewClaim:
    """
    Atomically claims or checks a review run based on the full identity:
    installation_id + owner + repo + pr_number + commit_sha.
    """
    conn = get_connection()

    try:
        with conn.cursor() as cursor:
            # First check legacy reviews table for COMPLETED
            full_repo = f"{owner}/{repo}"
            cursor.execute(
                """
                SELECT id, status FROM reviews
                WHERE repository = %s AND pr_number = %s AND commit_sha = %s
                """,
                (full_repo, pr_number, commit_sha),
            )
            legacy_row = cursor.fetchone()
            if legacy_row and legacy_row[1] == "COMPLETED":
                return ReviewClaim(claimed=False, review_id=str(legacy_row[0]), reason="already_completed")

            cursor.execute(
                """
                SELECT id, status, started_at, attempt_count
                FROM review_runs
                WHERE installation_id = %s
                  AND owner = %s
                  AND repo = %s
                  AND pr_number = %s
                  AND commit_sha = %s
                """,
                (installation_id, owner, repo, pr_number, commit_sha),
            )

            row = cursor.fetchone()

            if row:
                review_id, status, started_at, attempt_count = str(row[0]), row[1], row[2], row[3]

                if status == "COMPLETED":
                    return ReviewClaim(claimed=False, review_id=review_id, reason="already_completed")

                if status == "DEAD_LETTER":
                    return ReviewClaim(claimed=False, review_id=review_id, reason="dead_letter")


                in_progress = {"PROCESSING", "AI_REVIEWING", "VALIDATING", "POLICY_DECISION", "PUBLISHING"}
                if status in in_progress:
                    # Check if stale
                    now = datetime.now(timezone.utc)
                    if started_at and started_at.tzinfo is None:
                        started_at = started_at.replace(tzinfo=timezone.utc)

                    if started_at and (now - started_at).total_seconds() < REVIEW_STALE_TIMEOUT_SECONDS:
                        return ReviewClaim(claimed=False, review_id=review_id, reason="currently_processing")

                    # Stale -> reclaim
                    cursor.execute(
                        """
                        UPDATE review_runs
                        SET status = 'PROCESSING',
                            started_at = CURRENT_TIMESTAMP,
                            updated_at = CURRENT_TIMESTAMP,
                            attempt_count = attempt_count + 1
                        WHERE id = %s
                        """,
                        (review_id,),
                    )
                    conn.commit()
                    return ReviewClaim(claimed=True, review_id=review_id, reason="reclaimed_stale")

                # FAILED, QUEUED, RECEIVED -> reclaim/run
                cursor.execute(
                    """
                    UPDATE review_runs
                    SET status = 'PROCESSING',
                        started_at = CURRENT_TIMESTAMP,
                        updated_at = CURRENT_TIMESTAMP,
                        attempt_count = attempt_count + 1
                    WHERE id = %s
                    """,
                    (review_id,),
                )
                conn.commit()
                return ReviewClaim(claimed=True, review_id=review_id)

            # Insert new review_run
            new_id = str(uuid.uuid4())
            cursor.execute(
                """
                INSERT INTO review_runs (
                    id, installation_id, owner, repo, pr_number, commit_sha, status, attempt_count, started_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, 'PROCESSING', 1, CURRENT_TIMESTAMP)
                ON CONFLICT (installation_id, owner, repo, pr_number, commit_sha) DO NOTHING
                RETURNING id
                """,
                (new_id, installation_id, owner, repo, pr_number, commit_sha),
            )
            inserted = cursor.fetchone()
            conn.commit()

            if inserted:
                return ReviewClaim(claimed=True, review_id=new_id)

            # Race condition retry
            return claim_review_run(installation_id, owner, repo, pr_number, commit_sha)

    finally:
        conn.close()


def update_review_run_status(
    review_id: str,
    status: str,
    error_type: str | None = None,
    error_message: str | None = None,
) -> None:
    """Update status and timestamps for a review_run."""
    conn = get_connection()

    try:
        with conn.cursor() as cursor:
            if status in ("COMPLETED", "FAILED", "DEAD_LETTER"):
                cursor.execute(
                    """
                    UPDATE review_runs
                    SET status = %s,
                        error_type = COALESCE(%s, error_type),
                        error_message = COALESCE(%s, error_message),
                        completed_at = CURRENT_TIMESTAMP,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                    """,
                    (status, error_type, error_message, review_id),
                )
            else:
                cursor.execute(
                    """
                    UPDATE review_runs
                    SET status = %s,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                    """,
                    (status, review_id),
                )
        conn.commit()

    finally:
        conn.close()


def record_llm_usage(
    review_id: str,
    agent: str,
    model: str,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    total_tokens: int | None = None,
    estimated_cost: float | None = None,
) -> None:
    """Record LLM token usage and estimated cost for a review."""
    conn = get_connection()

    try:
        usage_id = str(uuid.uuid4())
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO llm_usage (
                    id, review_id, agent, model, input_tokens, output_tokens, total_tokens, estimated_cost
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (usage_id, review_id, agent, model, input_tokens, output_tokens, total_tokens, estimated_cost),
            )
        conn.commit()

    finally:
        conn.close()


def record_review_metrics(
    review_id: str,
    total_duration_ms: int | None = None,
    queue_wait_ms: int | None = None,
    checkout_duration_ms: int | None = None,
    agent_duration_ms: int | None = None,
    validation_duration_ms: int | None = None,
    test_duration_ms: int | None = None,
    publishing_duration_ms: int | None = None,
) -> None:
    """Record stage duration metrics for a review run."""
    conn = get_connection()

    try:
        metric_id = str(uuid.uuid4())
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO review_metrics (
                    id, review_id, total_duration_ms, queue_wait_ms, checkout_duration_ms,
                    agent_duration_ms, validation_duration_ms, test_duration_ms, publishing_duration_ms
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (review_id) DO UPDATE SET
                    total_duration_ms = COALESCE(EXCLUDED.total_duration_ms, review_metrics.total_duration_ms),
                    queue_wait_ms = COALESCE(EXCLUDED.queue_wait_ms, review_metrics.queue_wait_ms),
                    checkout_duration_ms = COALESCE(EXCLUDED.checkout_duration_ms, review_metrics.checkout_duration_ms),
                    agent_duration_ms = COALESCE(EXCLUDED.agent_duration_ms, review_metrics.agent_duration_ms),
                    validation_duration_ms = COALESCE(EXCLUDED.validation_duration_ms, review_metrics.validation_duration_ms),
                    test_duration_ms = COALESCE(EXCLUDED.test_duration_ms, review_metrics.test_duration_ms),
                    publishing_duration_ms = COALESCE(EXCLUDED.publishing_duration_ms, review_metrics.publishing_duration_ms)
                """,
                (
                    metric_id, review_id, total_duration_ms, queue_wait_ms, checkout_duration_ms,
                    agent_duration_ms, validation_duration_ms, test_duration_ms, publishing_duration_ms
                ),
            )
        conn.commit()

    finally:
        conn.close()
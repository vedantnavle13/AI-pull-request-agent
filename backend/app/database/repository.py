import json
import uuid

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
    force_new: bool = False,
) -> ReviewClaim:
    """
    Atomically claims or checks a review run based on the full identity:
    installation_id + owner + repo + pr_number + commit_sha.

    force_new=True: used when action='opened' (brand-new PR or re-opened after close).
    Resets any COMPLETED/FAILED row so the PR always gets a fresh review.
    """
    conn = get_connection()

    try:
        with conn.cursor() as cursor:
            full_repo = f"{owner}/{repo}"

            # Check legacy reviews table for COMPLETED — skip unless force_new.
            cursor.execute(
                """
                SELECT id, status FROM reviews
                WHERE repository = %s AND pr_number = %s AND commit_sha = %s
                """,
                (full_repo, pr_number, commit_sha),
            )
            legacy_row = cursor.fetchone()
            if legacy_row and legacy_row[1] == "COMPLETED" and not force_new:
                return ReviewClaim(claimed=False, review_id=str(legacy_row[0]), reason="already_completed")

            # If force_new and legacy row is COMPLETED, reset it so the worker can rerun.
            if legacy_row and legacy_row[1] == "COMPLETED" and force_new:
                cursor.execute(
                    "UPDATE reviews SET status = 'QUEUED', started_at = NULL, completed_at = NULL "
                    "WHERE id = %s",
                    (legacy_row[0],),
                )

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
                    if not force_new:
                        return ReviewClaim(claimed=False, review_id=review_id, reason="already_completed")
                    # force_new: reset to QUEUED so worker re-runs review for the new PR.
                    cursor.execute(
                        """
                        UPDATE review_runs
                        SET status = 'QUEUED', started_at = NULL, updated_at = CURRENT_TIMESTAMP, attempt_count = 0
                        WHERE id = %s
                        """,
                        (review_id,),
                    )
                    conn.commit()
                    return ReviewClaim(claimed=True, review_id=review_id, reason="force_new_reset")

                if status == "DEAD_LETTER" and not force_new:
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

            # Insert new review_run as QUEUED — only the worker transitions to PROCESSING.
            new_id = str(uuid.uuid4())
            cursor.execute(
                """
                INSERT INTO review_runs (
                    id, installation_id, owner, repo, pr_number, commit_sha, status, attempt_count
                )
                VALUES (%s, %s, %s, %s, %s, %s, 'QUEUED', 0)
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
    context_build_ms: int | None = None,
    agent_duration_ms: int | None = None,
    validation_duration_ms: int | None = None,
    test_duration_ms: int | None = None,
    publishing_duration_ms: int | None = None,
    auto_merge_ms: int | None = None,
    final_decision: str | None = None,
    final_status: str | None = None,
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
                    agent_duration_ms, validation_duration_ms, test_duration_ms, publishing_duration_ms,
                    context_build_ms, auto_merge_ms, final_decision, final_status
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (review_id) DO UPDATE SET
                    total_duration_ms      = COALESCE(EXCLUDED.total_duration_ms, review_metrics.total_duration_ms),
                    queue_wait_ms          = COALESCE(EXCLUDED.queue_wait_ms, review_metrics.queue_wait_ms),
                    checkout_duration_ms   = COALESCE(EXCLUDED.checkout_duration_ms, review_metrics.checkout_duration_ms),
                    context_build_ms       = COALESCE(EXCLUDED.context_build_ms, review_metrics.context_build_ms),
                    agent_duration_ms      = COALESCE(EXCLUDED.agent_duration_ms, review_metrics.agent_duration_ms),
                    validation_duration_ms = COALESCE(EXCLUDED.validation_duration_ms, review_metrics.validation_duration_ms),
                    test_duration_ms       = COALESCE(EXCLUDED.test_duration_ms, review_metrics.test_duration_ms),
                    publishing_duration_ms = COALESCE(EXCLUDED.publishing_duration_ms, review_metrics.publishing_duration_ms),
                    auto_merge_ms          = COALESCE(EXCLUDED.auto_merge_ms, review_metrics.auto_merge_ms),
                    final_decision         = COALESCE(EXCLUDED.final_decision, review_metrics.final_decision),
                    final_status           = COALESCE(EXCLUDED.final_status, review_metrics.final_status)
                """,
                (
                    metric_id, review_id, total_duration_ms, queue_wait_ms, checkout_duration_ms,
                    agent_duration_ms, validation_duration_ms, test_duration_ms, publishing_duration_ms,
                    context_build_ms, auto_merge_ms, final_decision, final_status
                ),
            )
        conn.commit()

    finally:
        conn.close()


# ===========================================================================
# Phase 13 — Auto-Merge Repository Functions
# ===========================================================================

def claim_merge(review_id: str) -> bool:
    """
    Atomically claim the right to attempt auto-merge for this review.

    Steps:
      1. INSERT a row with merge_status='MERGING' ON CONFLICT DO NOTHING.
         If inserted → we own it → return True.
      2. If conflict (row already exists), check current status:
         - MERGING / MERGED → another worker has it → return False.
         - FAILED / ABORTED  → retry allowed → UPDATE to MERGING → return True.

    The UNIQUE constraint on review_id prevents double-merge.
    """
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            # Try to transition ELIGIBLE → MERGING atomically.
            cur.execute(
                """
                UPDATE auto_merges
                SET    merge_status     = 'MERGING',
                       merge_started_at = NOW(),
                       merge_attempts   = merge_attempts + 1,
                       updated_at       = NOW()
                WHERE  review_id    = %s
                  AND  merge_status IN ('ELIGIBLE', 'FAILED')
                RETURNING id
                """,
                (review_id,),
            )
            row = cur.fetchone()
        conn.commit()
        return row is not None
    finally:
        conn.close()


def record_merge_result(
    review_id: str,
    merge_status: str,
    *,
    current_sha: str | None = None,
    merge_commit_sha: str | None = None,
    checks_status: str | None = None,
    error: str | None = None,
) -> None:
    """
    Persist the outcome of an auto-merge attempt.
    Called after the GitHub merge API returns (success or failure).
    """
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE auto_merges
                SET    merge_status       = %s,
                       merge_completed_at = CASE WHEN %s IN ('MERGED', 'FAILED', 'ABORTED')
                                                 THEN NOW() ELSE merge_completed_at END,
                       merge_commit_sha   = COALESCE(%s, merge_commit_sha),
                       current_sha        = COALESCE(%s, current_sha),
                       checks_status      = COALESCE(%s, checks_status),
                       error              = COALESCE(%s, error),
                       updated_at         = NOW()
                WHERE  review_id = %s
                """,
                (
                    merge_status,
                    merge_status,
                    merge_commit_sha,
                    current_sha,
                    checks_status,
                    error,
                    review_id,
                ),
            )
        conn.commit()
    finally:
        conn.close()


def create_merge_record(
    review_id: str,
    repository: str,
    pr_number: int,
    reviewed_sha: str,
    decision: str,
    merge_status: str = "NOT_ELIGIBLE",
    merge_method: str | None = None,
) -> None:
    """
    Insert the initial auto_merges row when the gate is first evaluated.
    Uses ON CONFLICT DO NOTHING for idempotency (e.g. ARQ retries).
    """
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO auto_merges (
                    review_id, repository, pr_number, reviewed_sha,
                    decision, merge_status, merge_method
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (review_id) DO NOTHING
                """,
                (review_id, repository, pr_number, reviewed_sha,
                 decision, merge_status, merge_method),
            )
        conn.commit()
    finally:
        conn.close()


def get_merge_record(review_id: str) -> dict | None:
    """Return the auto_merges row for the given review_id, or None."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT review_id, repository, pr_number, reviewed_sha,
                       current_sha, decision, merge_status, merge_method,
                       checks_status, merge_attempts, merge_started_at,
                       merge_completed_at, merge_sha, merge_commit_sha, error
                FROM   auto_merges
                WHERE  review_id = %s
                """,
                (review_id,),
            )
            row = cur.fetchone()
        if row is None:
            return None
        keys = [
            "review_id", "repository", "pr_number", "reviewed_sha",
            "current_sha", "decision", "merge_status", "merge_method",
            "checks_status", "merge_attempts", "merge_started_at",
            "merge_completed_at", "merge_sha", "merge_commit_sha", "error",
        ]
        return dict(zip(keys, row))
    finally:
        conn.close()


# ===========================================================================
# Phase 14 — Observability & Economics Repository Functions
# ===========================================================================

def record_agent_metrics(
    review_id: str,
    agent_name: str,
    *,
    started_at=None,
    completed_at=None,
    duration_ms: int | None = None,
    success: bool = True,
    finding_count: int = 0,
    error_type: str | None = None,
    error_message: str | None = None,
) -> None:
    """Record timing and result metrics for a single agent run."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO agent_metrics (
                    review_id, agent_name, started_at, completed_at,
                    duration_ms, success, finding_count, error_type, error_message
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    review_id, agent_name, started_at, completed_at,
                    duration_ms, success, finding_count, error_type, error_message,
                ),
            )
        conn.commit()
    finally:
        conn.close()


def record_error_metric(
    stage: str,
    error_category: str,
    *,
    review_id: str | None = None,
    error_type: str | None = None,
    error_message: str | None = None,
    retryable: bool = False,
    attempt: int = 1,
) -> None:
    """Record a structured error event for failure analysis."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO error_metrics (
                    review_id, stage, error_category, error_type, error_message, retryable, attempt
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (review_id, stage, error_category, error_type, error_message, retryable, attempt),
            )
        conn.commit()
    finally:
        conn.close()


def get_overview_metrics(repository: str | None = None) -> dict:
    """
    Return aggregate review statistics for the dashboard overview.
    Optionally filtered by repository (owner/repo format).

    NOTE: Uses review_runs (UUID primary key) and review_metrics (UUID FK).
    The legacy 'reviews' table uses integer IDs and cannot join review_metrics.
    """
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            # Build repository filter for review_runs
            # repository format: 'owner/repo' -> split into owner + repo
            if repository and '/' in repository:
                owner_filter, repo_filter = repository.split('/', 1)
                repo_params = (owner_filter, repo_filter)
                rr_filter = "AND rr.owner = %s AND rr.repo = %s"
            else:
                repo_params = ()
                rr_filter = ""

            cur.execute(
                f"""
                SELECT
                    COUNT(*)                                                   AS reviews_total,
                    COUNT(*) FILTER (WHERE rr.status = 'COMPLETED')            AS completed,
                    COUNT(*) FILTER (WHERE rr.status = 'FAILED')               AS failed,
                    COUNT(*) FILTER (WHERE rr.status = 'DEAD_LETTER')          AS dead_letter,
                    COUNT(*) FILTER (WHERE rm.final_decision = 'APPROVE')      AS approve,
                    COUNT(*) FILTER (WHERE rm.final_decision = 'HUMAN_REVIEW') AS human_review,
                    COUNT(*) FILTER (WHERE rm.final_decision = 'BLOCK')        AS block,
                    ROUND(AVG(rm.total_duration_ms))                           AS avg_latency_ms,
                    PERCENTILE_CONT(0.5) WITHIN GROUP
                        (ORDER BY rm.total_duration_ms)                        AS p50_latency_ms,
                    PERCENTILE_CONT(0.95) WITHIN GROUP
                        (ORDER BY rm.total_duration_ms)                        AS p95_latency_ms,
                    COALESCE(SUM(rr.attempt_count - 1), 0)                     AS total_retries
                FROM   review_runs rr
                LEFT JOIN review_metrics rm ON rm.review_id = rr.id
                WHERE  1=1 {rr_filter}
                """,
                repo_params,
            )
            row = cur.fetchone()

            cur.execute(
                """
                SELECT COUNT(*) FILTER (WHERE merge_status = 'MERGED'),
                       COUNT(*) FILTER (WHERE merge_status = 'FAILED')
                FROM   auto_merges
                """
            )
            merge_row = cur.fetchone()

            cur.execute(
                """
                SELECT COALESCE(SUM(estimated_cost), 0),
                       CASE WHEN COUNT(DISTINCT review_id) > 0
                            THEN SUM(estimated_cost) / COUNT(DISTINCT review_id)
                            ELSE NULL END
                FROM   llm_usage
                WHERE  estimated_cost IS NOT NULL
                """
            )
            cost_row = cur.fetchone()

        if not row:
            return {}

        return {
            "reviews_total":    int(row[0] or 0),
            "completed":        int(row[1] or 0),
            "failed":           int(row[2] or 0),
            "dead_letter":      int(row[3] or 0),
            "approve":          int(row[4] or 0),
            "human_review":     int(row[5] or 0),
            "block":            int(row[6] or 0),
            "avg_latency_ms":   int(row[7]) if row[7] is not None else None,
            "p50_latency_ms":   int(row[8]) if row[8] is not None else None,
            "p95_latency_ms":   int(row[9]) if row[9] is not None else None,
            "total_retries":    int(row[10] or 0),
            "auto_merged":      int(merge_row[0] or 0) if merge_row else 0,
            "auto_merge_failed":int(merge_row[1] or 0) if merge_row else 0,
            "total_cost_usd":   float(cost_row[0]) if cost_row and cost_row[0] else None,
            "avg_cost_usd":     float(cost_row[1]) if cost_row and cost_row[1] else None,
        }
    finally:
        conn.close()


def get_review_detail_metrics(review_id: str) -> dict | None:
    """
    Return detailed timing, agent, LLM usage and cost for one review.

    Accepts:
    - UUID (from review_runs.id) — preferred
    - Plain string that might be a UUID with dashes stripped
    If not found by UUID, returns None (the legacy 'reviews' integer ID
    is not supported here; callers should use the UUID from review_runs).
    """
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            # Core review — pull from review_runs + review_metrics
            cur.execute(
                """
                SELECT rr.id, rr.owner, rr.repo, rr.pr_number, rr.commit_sha,
                       rr.status, rm.total_duration_ms, rm.queue_wait_ms,
                       rm.checkout_duration_ms, rm.context_build_ms,
                       rm.agent_duration_ms, rm.validation_duration_ms,
                       rm.test_duration_ms, rm.publishing_duration_ms,
                       rm.auto_merge_ms, rm.final_decision, rm.final_status,
                       rr.created_at, rr.started_at, rr.completed_at,
                       rr.attempt_count, rr.error_type
                FROM   review_runs rr
                LEFT JOIN review_metrics rm ON rm.review_id = rr.id
                WHERE  rr.id::text = %s
                """,
                (review_id,),
            )
            rr = cur.fetchone()
            if not rr:
                return None

            # Per-agent metrics
            cur.execute(
                """
                SELECT agent_name, duration_ms, success, finding_count,
                       error_type, started_at, completed_at
                FROM   agent_metrics
                WHERE  review_id::text = %s
                ORDER BY started_at ASC NULLS LAST
                """,
                (review_id,),
            )
            agents_raw = cur.fetchall()

            # LLM usage
            cur.execute(
                """
                SELECT agent, model, input_tokens, output_tokens, total_tokens, estimated_cost
                FROM   llm_usage
                WHERE  review_id = %s
                ORDER BY agent
                """,
                (review_id,),
            )
            llm_raw = cur.fetchall()

        agents = {}
        for row in agents_raw:
            agents[row[0]] = {
                "duration_ms":   row[1],
                "success":       row[2],
                "finding_count": row[3],
                "error_type":    row[4],
                "started_at":    row[5].isoformat() if row[5] else None,
                "completed_at":  row[6].isoformat() if row[6] else None,
            }

        llm_usage = []
        total_cost = 0.0
        has_cost = False
        for row in llm_raw:
            cost = float(row[5]) if row[5] is not None else None
            if cost is not None:
                total_cost += cost
                has_cost = True
            llm_usage.append({
                "agent":         row[0],
                "model":         row[1],
                "input_tokens":  row[2],
                "output_tokens": row[3],
                "total_tokens":  row[4],
                "estimated_cost":cost,
            })

        # Compute parallel wall-clock agent time = max of concurrent agent durations
        parallel_wall_ms = None
        if agents:
            agent_durations = [v["duration_ms"] for v in agents.values() if v["duration_ms"] is not None]
            if agent_durations:
                parallel_wall_ms = max(agent_durations)

        return {
            "review_id":            str(rr[0]),
            "owner":                rr[1],
            "repo":                 rr[2],
            "repository":           f"{rr[1]}/{rr[2]}",
            "pr_number":            rr[3],
            "commit_sha":           rr[4],
            "status":               rr[5],
            "timings": {
                "total_ms":             rr[6],
                "queue_wait_ms":        rr[7],
                "checkout_ms":          rr[8],
                "context_build_ms":     rr[9],
                "agent_wall_clock_ms":  rr[10],      # total wall clock for all 4 agents
                "parallel_agent_ms":    parallel_wall_ms,  # max(individual agent durations)
                "validation_ms":        rr[11],
                "test_ms":              rr[12],
                "publish_ms":           rr[13],
                "auto_merge_ms":        rr[14],
            },
            "final_decision":       rr[15],
            "final_status":         rr[16],
            "queued_at":            rr[17].isoformat() if rr[17] else None,
            "started_at":           rr[18].isoformat() if rr[18] else None,
            "completed_at":         rr[19].isoformat() if rr[19] else None,
            "retry_count":          int(rr[20] - 1) if rr[20] is not None else 0,
            "error_type":           rr[21],
            "agents":               agents,
            "llm_usage":            llm_usage,
            "total_cost_usd":       round(total_cost, 8) if has_cost else None,
        }

    finally:
        conn.close()


def get_agent_metrics_summary() -> list[dict]:
    """Return per-agent aggregate performance statistics."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    agent_name,
                    COUNT(*)                                     AS executions,
                    ROUND(AVG(duration_ms))                      AS avg_duration_ms,
                    PERCENTILE_CONT(0.95) WITHIN GROUP
                        (ORDER BY duration_ms)                   AS p95_duration_ms,
                    ROUND(100.0 * AVG(CASE WHEN success THEN 1.0 ELSE 0.0 END), 1) AS success_rate_pct,
                    ROUND(AVG(finding_count), 2)                 AS avg_findings
                FROM   agent_metrics
                GROUP BY agent_name
                ORDER BY agent_name
                """
            )
            rows = cur.fetchall()
        return [
            {
                "agent":            row[0],
                "executions":       int(row[1]),
                "avg_duration_ms":  int(row[2]) if row[2] is not None else None,
                "p95_duration_ms":  int(row[3]) if row[3] is not None else None,
                "success_rate_pct": float(row[4]) if row[4] is not None else None,
                "avg_findings":     float(row[5]) if row[5] is not None else None,
            }
            for row in rows
        ]
    finally:
        conn.close()


def get_cost_summary() -> dict:
    """Return cost totals, per-agent breakdown, and per-model breakdown."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            # Total and per-review average
            cur.execute(
                """
                SELECT
                    COALESCE(SUM(estimated_cost), 0)       AS total_cost,
                    COUNT(DISTINCT review_id)              AS reviews_with_cost,
                    CASE WHEN COUNT(DISTINCT review_id) > 0
                         THEN SUM(estimated_cost) / COUNT(DISTINCT review_id)
                         ELSE NULL END                     AS avg_cost_per_review,
                    COALESCE(SUM(CASE WHEN created_at >= NOW() - INTERVAL '1 day'
                                     THEN estimated_cost END), 0) AS daily_cost
                FROM   llm_usage
                WHERE  estimated_cost IS NOT NULL
                """
            )
            total_row = cur.fetchone()

            # Per-agent breakdown
            cur.execute(
                """
                SELECT agent, COALESCE(SUM(estimated_cost), 0),
                       COALESCE(SUM(input_tokens), 0), COALESCE(SUM(output_tokens), 0)
                FROM   llm_usage
                WHERE  estimated_cost IS NOT NULL
                GROUP BY agent ORDER BY agent
                """
            )
            agent_rows = cur.fetchall()

            # Per-model breakdown
            cur.execute(
                """
                SELECT model, COALESCE(SUM(estimated_cost), 0),
                       COALESCE(SUM(input_tokens), 0), COALESCE(SUM(output_tokens), 0),
                       COUNT(*) AS calls
                FROM   llm_usage
                WHERE  estimated_cost IS NOT NULL
                GROUP BY model ORDER BY model
                """
            )
            model_rows = cur.fetchall()

        return {
            "total_cost_usd":       float(total_row[0]) if total_row else 0.0,
            "reviews_with_cost":    int(total_row[1]) if total_row else 0,
            "avg_cost_per_review":  float(total_row[2]) if total_row and total_row[2] else None,
            "daily_cost_usd":       float(total_row[3]) if total_row else 0.0,
            "by_agent": [
                {
                    "agent":         row[0],
                    "cost_usd":      float(row[1]),
                    "input_tokens":  int(row[2]),
                    "output_tokens": int(row[3]),
                }
                for row in agent_rows
            ],
            "by_model": [
                {
                    "model":         row[0],
                    "cost_usd":      float(row[1]),
                    "input_tokens":  int(row[2]),
                    "output_tokens": int(row[3]),
                    "calls":         int(row[4]),
                }
                for row in model_rows
            ],
        }
    finally:
        conn.close()


def get_percentile_latency(percentile: float, repository: str | None = None) -> float | None:
    """Return p50/p95/p99 latency in ms across all completed reviews."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            if repository:
                cur.execute(
                    """
                    SELECT PERCENTILE_CONT(%s) WITHIN GROUP (ORDER BY rm.total_duration_ms)
                    FROM   review_metrics rm
                    JOIN   review_runs rr ON rr.id = rm.review_id
                    WHERE  (rr.owner || '/' || rr.repo) = %s
                      AND  rm.total_duration_ms IS NOT NULL
                    """,
                    (percentile, repository),
                )
            else:
                cur.execute(
                    """
                    SELECT PERCENTILE_CONT(%s) WITHIN GROUP (ORDER BY total_duration_ms)
                    FROM   review_metrics
                    WHERE  total_duration_ms IS NOT NULL
                    """,
                    (percentile,),
                )
            row = cur.fetchone()
        return float(row[0]) if row and row[0] is not None else None
    finally:
        conn.close()


# ===========================================================================
# Phase 3 — Multi-user SaaS Repository Functions
# ===========================================================================

def upsert_user(
    github_user_id: int,
    github_username: str,
    github_avatar_url: str | None = None,
    email: str | None = None,
) -> dict:
    """
    Insert or update an application user identified by their GitHub user ID.

    Returns the full user row as a dict.
    Idempotent: safe to call on every OAuth login.
    """
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO users (
                    github_user_id,
                    github_username,
                    github_avatar_url,
                    email
                )
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (github_user_id)
                DO UPDATE SET
                    github_username   = EXCLUDED.github_username,
                    github_avatar_url = EXCLUDED.github_avatar_url,
                    email             = COALESCE(EXCLUDED.email, users.email),
                    updated_at        = NOW()
                RETURNING id, github_user_id, github_username, github_avatar_url, email,
                          created_at, updated_at
                """,
                (github_user_id, github_username, github_avatar_url, email),
            )
            row = cur.fetchone()
        conn.commit()
        return {
            "id":                str(row[0]),
            "github_user_id":    row[1],
            "github_username":   row[2],
            "github_avatar_url": row[3],
            "email":             row[4],
            "created_at":        row[5].isoformat() if row[5] else None,
            "updated_at":        row[6].isoformat() if row[6] else None,
        }
    finally:
        conn.close()


def get_user_by_github_id(github_user_id: int) -> dict | None:
    """Return the application user with the given GitHub user ID, or None."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, github_user_id, github_username, github_avatar_url, email,
                       created_at, updated_at
                FROM   users
                WHERE  github_user_id = %s
                """,
                (github_user_id,),
            )
            row = cur.fetchone()
        if row is None:
            return None
        return {
            "id":                str(row[0]),
            "github_user_id":    row[1],
            "github_username":   row[2],
            "github_avatar_url": row[3],
            "email":             row[4],
            "created_at":        row[5].isoformat() if row[5] else None,
            "updated_at":        row[6].isoformat() if row[6] else None,
        }
    finally:
        conn.close()


def get_user_by_id(user_id: str) -> dict | None:
    """Return an application user by their internal UUID, or None."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, github_user_id, github_username, github_avatar_url, email,
                       created_at, updated_at
                FROM   users
                WHERE  id = %s
                """,
                (user_id,),
            )
            row = cur.fetchone()
        if row is None:
            return None
        return {
            "id":                str(row[0]),
            "github_user_id":    row[1],
            "github_username":   row[2],
            "github_avatar_url": row[3],
            "email":             row[4],
            "created_at":        row[5].isoformat() if row[5] else None,
            "updated_at":        row[6].isoformat() if row[6] else None,
        }
    finally:
        conn.close()


def upsert_github_installation(
    user_id: str,
    installation_id: int,
    account_id: int,
    account_login: str,
    account_type: str,
) -> dict:
    """
    Insert or update a GitHub App installation for the given user.

    installation_id has a UNIQUE constraint, so if it already exists for
    *another* user we raise an integrity error (which the caller should handle).

    Returns the full installation row as a dict.
    Idempotent: safe to call repeatedly with the same installation_id.
    """
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO github_installations (
                    user_id,
                    installation_id,
                    account_id,
                    account_login,
                    account_type
                )
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (installation_id)
                DO UPDATE SET
                    account_id    = EXCLUDED.account_id,
                    account_login = EXCLUDED.account_login,
                    account_type  = EXCLUDED.account_type,
                    updated_at    = NOW()
                RETURNING id, user_id, installation_id, account_id, account_login,
                          account_type, created_at, updated_at
                """,
                (user_id, installation_id, account_id, account_login, account_type),
            )
            row = cur.fetchone()
        conn.commit()
        return {
            "id":              str(row[0]),
            "user_id":         str(row[1]),
            "installation_id": row[2],
            "account_id":      row[3],
            "account_login":   row[4],
            "account_type":    row[5],
            "created_at":      row[6].isoformat() if row[6] else None,
            "updated_at":      row[7].isoformat() if row[7] else None,
        }
    finally:
        conn.close()


def get_installation_by_installation_id(installation_id: int) -> dict | None:
    """
    Return the github_installations row for the given numeric installation_id.

    Returns None if this installation has not been registered yet (e.g. the
    webhook arrived before the installation callback was processed).
    """
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, user_id, installation_id, account_id, account_login,
                       account_type, created_at, updated_at
                FROM   github_installations
                WHERE  installation_id = %s
                """,
                (installation_id,),
            )
            row = cur.fetchone()
        if row is None:
            return None
        return {
            "id":              str(row[0]),
            "user_id":         str(row[1]),
            "installation_id": row[2],
            "account_id":      row[3],
            "account_login":   row[4],
            "account_type":    row[5],
            "created_at":      row[6].isoformat() if row[6] else None,
            "updated_at":      row[7].isoformat() if row[7] else None,
        }
    finally:
        conn.close()


def get_installations_for_user(user_id: str) -> list[dict]:
    """Return all GitHub App installations belonging to a user."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, user_id, installation_id, account_id, account_login,
                       account_type, created_at, updated_at
                FROM   github_installations
                WHERE  user_id = %s
                ORDER BY created_at DESC
                """,
                (user_id,),
            )
            rows = cur.fetchall()
        return [
            {
                "id":              str(r[0]),
                "user_id":         str(r[1]),
                "installation_id": r[2],
                "account_id":      r[3],
                "account_login":   r[4],
                "account_type":    r[5],
                "created_at":      r[6].isoformat() if r[6] else None,
                "updated_at":      r[7].isoformat() if r[7] else None,
            }
            for r in rows
        ]
    finally:
        conn.close()


def get_user_id_for_installation(installation_id: int) -> str | None:
    """
    Given a numeric GitHub installation_id, return the associated user_id UUID.
    Returns None if the installation is not registered.
    """
    inst = get_installation_by_installation_id(installation_id)
    return inst["user_id"] if inst else None


def upsert_repository(
    installation_uuid: str,
    github_repo_id: int,
    owner: str,
    name: str,
    full_name: str,
    private: bool = False,
    default_branch: str = "main",
) -> dict:
    """
    Insert or update a repository record for a given installation (UUID FK).

    Idempotent: safe to call every time repositories are synced.
    The UNIQUE constraint is (installation_id, github_repo_id).
    """
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO repositories (
                    installation_id,
                    github_repo_id,
                    owner,
                    name,
                    full_name,
                    private,
                    default_branch,
                    active
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, TRUE)
                ON CONFLICT (installation_id, github_repo_id)
                DO UPDATE SET
                    owner          = EXCLUDED.owner,
                    name           = EXCLUDED.name,
                    full_name      = EXCLUDED.full_name,
                    private        = EXCLUDED.private,
                    default_branch = EXCLUDED.default_branch,
                    active         = TRUE,
                    updated_at     = NOW()
                RETURNING id, installation_id, github_repo_id, owner, name, full_name,
                          private, default_branch, active, created_at, updated_at
                """,
                (
                    installation_uuid, github_repo_id, owner, name,
                    full_name, private, default_branch,
                ),
            )
            row = cur.fetchone()
        conn.commit()
        return {
            "id":              str(row[0]),
            "installation_id": str(row[1]),
            "github_repo_id":  row[2],
            "owner":           row[3],
            "name":            row[4],
            "full_name":       row[5],
            "private":         row[6],
            "default_branch":  row[7],
            "active":          row[8],
            "created_at":      row[9].isoformat() if row[9] else None,
            "updated_at":      row[10].isoformat() if row[10] else None,
        }
    finally:
        conn.close()


def get_repositories_for_installation(installation_uuid: str) -> list[dict]:
    """Return all active repositories for a given installation UUID."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, installation_id, github_repo_id, owner, name, full_name,
                       private, default_branch, active, created_at, updated_at
                FROM   repositories
                WHERE  installation_id = %s
                  AND  active = TRUE
                ORDER BY full_name ASC
                """,
                (installation_uuid,),
            )
            rows = cur.fetchall()
        return [
            {
                "id":              str(r[0]),
                "installation_id": str(r[1]),
                "github_repo_id":  r[2],
                "owner":           r[3],
                "name":            r[4],
                "full_name":       r[5],
                "private":         r[6],
                "default_branch":  r[7],
                "active":          r[8],
                "created_at":      r[9].isoformat() if r[9] else None,
                "updated_at":      r[10].isoformat() if r[10] else None,
            }
            for r in rows
        ]
    finally:
        conn.close()


def get_repositories_for_user(user_id: str) -> list[dict]:
    """
    Return all active repositories accessible to a user, joining through
    their installations.

    The query joins: users → github_installations → repositories.
    A user can only see their own repositories.
    """
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT r.id, r.installation_id, r.github_repo_id, r.owner, r.name,
                       r.full_name, r.private, r.default_branch, r.active,
                       r.created_at, r.updated_at,
                       gi.account_login, gi.installation_id AS installation_id_int
                FROM   repositories r
                JOIN   github_installations gi ON gi.id = r.installation_id
                WHERE  gi.user_id = %s
                  AND  r.active = TRUE
                ORDER BY r.full_name ASC
                """,
                (user_id,),
            )
            rows = cur.fetchall()
        return [
            {
                "id":              str(r[0]),
                "installation_id": str(r[1]),
                "github_repo_id":  r[2],
                "owner":           r[3],
                "name":            r[4],
                "full_name":       r[5],
                "private":         r[6],
                "default_branch":  r[7],
                "active":          r[8],
                "created_at":      r[9].isoformat() if r[9] else None,
                "updated_at":      r[10].isoformat() if r[10] else None,
                "account_login":   r[11],
                "installation_id_int": r[12],
            }
            for r in rows
        ]
    finally:
        conn.close()


def verify_repository_belongs_to_user(user_id: str, full_name: str) -> bool:
    """
    Return True iff the repository (by full_name e.g. 'owner/repo') is
    accessible to the given user through at least one of their installations.

    This is the ownership gate for user-facing data access.
    """
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT 1
                FROM   repositories r
                JOIN   github_installations gi ON gi.id = r.installation_id
                WHERE  gi.user_id  = %s
                  AND  r.full_name = %s
                  AND  r.active    = TRUE
                LIMIT 1
                """,
                (user_id, full_name),
            )
            return cur.fetchone() is not None
    finally:
        conn.close()


def get_reviews_for_user(
    user_id: str,
    limit: int = 50,
    full_name: str | None = None,
) -> list[dict]:
    """
    Return recent review_runs for all repositories owned by the user.

    Joins: github_installations → review_runs using installation_id (int).
    Optionally filtered to a single repository by full_name.

    Ownership is enforced at the SQL level — a user can only see rows
    belonging to their own installations.

    Returns a list of dicts with review_run fields plus full_name.
    """
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            params: list = [user_id]
            repo_filter = ""
            if full_name:
                repo_filter = "AND (rr.owner || '/' || rr.repo) = %s"
                params.append(full_name)
            params.append(limit)

            cur.execute(
                f"""
                SELECT
                    rr.id,
                    rr.installation_id,
                    rr.owner,
                    rr.repo,
                    rr.pr_number,
                    rr.commit_sha,
                    rr.status,
                    rr.attempt_count,
                    rr.created_at,
                    rr.started_at,
                    rr.completed_at,
                    rr.updated_at,
                    rr.error_type,
                    rr.error_message
                FROM   review_runs rr
                JOIN   github_installations gi
                       ON gi.installation_id = rr.installation_id
                WHERE  gi.user_id = %s
                {repo_filter}
                ORDER BY rr.created_at DESC
                LIMIT  %s
                """,
                params,
            )
            rows = cur.fetchall()
        return [
            {
                "id":              str(r[0]),
                "installation_id": r[1],
                "owner":           r[2],
                "repo":            r[3],
                "full_name":       f"{r[2]}/{r[3]}",
                "pr_number":       r[4],
                "commit_sha":      r[5],
                "status":          r[6],
                "attempt_count":   r[7],
                "created_at":      r[8].isoformat() if r[8] else None,
                "started_at":      r[9].isoformat() if r[9] else None,
                "completed_at":    r[10].isoformat() if r[10] else None,
                "updated_at":      r[11].isoformat() if r[11] else None,
                "error_type":      r[12],
                "error_message":   r[13],
            }
            for r in rows
        ]
    finally:
        conn.close()
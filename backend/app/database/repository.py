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
from app.database.postgres import get_connection


def already_reviewed(
    repository: str,
    pr_number: int,
    commit_sha: str,
) -> bool:

    with get_connection() as conn:

        with conn.cursor() as cursor:

            cursor.execute(
                """
                SELECT 1
                FROM review_events
                WHERE repository = %s
                  AND pr_number = %s
                  AND commit_sha = %s
                LIMIT 1;
                """,
                (
                    repository,
                    pr_number,
                    commit_sha,
                ),
            )

            return cursor.fetchone() is not None


def create_review_event(
    repository: str,
    pr_number: int,
    commit_sha: str,
    status: str,
    decision: str | None = None,
):

    with get_connection() as conn:

        with conn.cursor() as cursor:

            cursor.execute(
                """
                INSERT INTO review_events (
                    repository,
                    pr_number,
                    commit_sha,
                    status,
                    decision
                )
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (
                    repository,
                    pr_number,
                    commit_sha
                )
                DO NOTHING
                RETURNING id;
                """,
                (
                    repository,
                    pr_number,
                    commit_sha,
                    status,
                    decision,
                ),
            )

            result = cursor.fetchone()

        conn.commit()

        return result[0] if result else None



def register_webhook_delivery(
    delivery_id: str,
    event_type: str | None,
    action: str | None,
) -> bool:

    with get_connection() as conn:

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
                RETURNING delivery_id;
                """,
                (
                    delivery_id,
                    event_type,
                    action,
                ),
            )

            result = cursor.fetchone()

        conn.commit()

        return result is not None        
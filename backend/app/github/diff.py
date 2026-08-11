import re

# Matches unified-diff hunk headers: @@ -old_start[,old_len] +new_start[,new_len] @@
_HUNK_HEADER_RE = re.compile(r"^@@\s+-\d+(?:,\d+)?\s+\+(\d+)(?:,\d+)?\s+@@", re.MULTILINE)


def _normalize_path(path: str | None) -> str:
    """Normalize file paths for consistent comparison (strip ./, /, backslashes)."""
    if not path:
        return ""
    p = str(path).strip().replace("\\", "/")
    while p.startswith("./") or p.startswith("/"):
        if p.startswith("./"):
            p = p[2:]
        elif p.startswith("/"):
            p = p[1:]
    return p


def extract_diff(files):

    changes = []

    for file in files:

        changes.append({
            "filename": file["filename"],
            "status": file["status"],
            "additions": file["additions"],
            "deletions": file["deletions"],
            "patch": file.get("patch", ""),
        })

    return changes


def get_changed_lines(patch: str) -> set[int]:
    """
    Parse a GitHub unified-diff patch string and return the set of
    new-file (RIGHT / addition side) line numbers that are part of
    this diff.

    Only lines prefixed with ' ' (context) or '+' (added) are counted
    as valid RIGHT-side positions; '-' lines are old-side only.

    Example:
        patch = "@@ -2,4 +2,5 @@ ...\n context\n+added\n context"
        get_changed_lines(patch) -> {2, 3, 4}

    Returns an empty set when the patch is empty or cannot be parsed.
    """

    if not patch:
        return set()

    changed: set[int] = set()
    current_line = 0

    for raw_line in patch.splitlines():
        # ── Hunk header ─────────────────────────────────────────────
        hunk_match = _HUNK_HEADER_RE.match(raw_line)
        if hunk_match:
            current_line = int(hunk_match.group(1))
            # If the hunk starts at 0 it means a newly-created file
            # with no context; normalise to 1.
            if current_line == 0:
                current_line = 1
            continue

        # ── Removed line (old side only) ────────────────────────────
        if raw_line.startswith("-"):
            # Does NOT advance new-file line counter.
            continue

        # ── Added line ──────────────────────────────────────────────
        if raw_line.startswith("+"):
            changed.add(current_line)
            current_line += 1
            continue

        # ── Context line (unchanged, present on both sides) ─────────
        if raw_line.startswith(" ") or raw_line == "":
            # Context lines are valid inline-comment positions on GitHub.
            changed.add(current_line)
            current_line += 1
            continue

        # Anything else (e.g. "\ No newline at end of file") — skip.

    return changed
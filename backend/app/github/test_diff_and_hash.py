"""
Phase 11 — Tests for get_changed_lines() and finding_hash().

Zero network calls. Zero Gemini calls. Pure logic.
"""

import pytest

from app.github.diff import get_changed_lines
from app.github.review import finding_hash


# ===========================================================================
# get_changed_lines() tests
# ===========================================================================

class TestGetChangedLines:

    def test_empty_patch(self):
        assert get_changed_lines("") == set()

    def test_none_like_empty(self):
        assert get_changed_lines("") == set()

    def test_simple_addition(self):
        patch = "@@ -1,3 +1,4 @@\n context\n+added line\n context\n context"
        lines = get_changed_lines(patch)
        # new_start=1, so lines 1,2,3,4 (context+added+context+context)
        assert 2 in lines   # added line is line 2
        assert 1 in lines   # context line 1
        assert 3 in lines   # context line 3

    def test_added_only_lines_included(self):
        patch = "@@ -0,0 +1,3 @@\n+line one\n+line two\n+line three"
        lines = get_changed_lines(patch)
        assert lines == {1, 2, 3}

    def test_removed_lines_not_included(self):
        patch = "@@ -1,3 +1,2 @@\n context\n-removed line\n context"
        lines = get_changed_lines(patch)
        # Only context lines 1 and 2 are on the new side.
        assert lines == {1, 2}

    def test_multiple_hunks(self):
        patch = (
            "@@ -1,2 +1,3 @@\n context\n+new line\n context\n"
            "@@ -10,2 +11,3 @@\n context\n+another new\n context"
        )
        lines = get_changed_lines(patch)
        assert 2 in lines    # added in first hunk
        assert 12 in lines   # added in second hunk

    def test_hunk_at_line_10(self):
        patch = "@@ -10,3 +10,4 @@\n context\n+added\n context\n context"
        lines = get_changed_lines(patch)
        assert 11 in lines   # the +added line is at new line 11

    def test_no_change_context_only(self):
        # A patch with only context (unchanged diff) — lines still counted.
        patch = "@@ -5,3 +5,3 @@\n context a\n context b\n context c"
        lines = get_changed_lines(patch)
        assert lines == {5, 6, 7}

    def test_line_not_in_diff_when_outside_hunk(self):
        patch = "@@ -1,3 +1,3 @@\n line1\n line2\n line3"
        lines = get_changed_lines(patch)
        # Line 100 is far outside the hunk.
        assert 100 not in lines


# ===========================================================================
# finding_hash() tests
# ===========================================================================

class TestFindingHash:

    def test_same_inputs_same_hash(self):
        h1 = finding_hash("owner/repo", 42, "abc123", "main.py", 10, "bug", "desc")
        h2 = finding_hash("owner/repo", 42, "abc123", "main.py", 10, "bug", "desc")
        assert h1 == h2

    def test_different_commit_sha_different_hash(self):
        h1 = finding_hash("owner/repo", 42, "abc123", "main.py", 10, "bug", "desc")
        h2 = finding_hash("owner/repo", 42, "xyz999", "main.py", 10, "bug", "desc")
        assert h1 != h2

    def test_different_line_different_hash(self):
        h1 = finding_hash("owner/repo", 42, "abc", "main.py", 10, "bug", "desc")
        h2 = finding_hash("owner/repo", 42, "abc", "main.py", 11, "bug", "desc")
        assert h1 != h2

    def test_different_file_different_hash(self):
        h1 = finding_hash("owner/repo", 42, "abc", "a.py", 10, "bug", "desc")
        h2 = finding_hash("owner/repo", 42, "abc", "b.py", 10, "bug", "desc")
        assert h1 != h2

    def test_hash_is_40_chars_hex(self):
        h = finding_hash("repo", 1, "sha", "file.py", 1, "cat", "desc")
        assert len(h) == 40
        int(h, 16)   # must be valid hex

    def test_none_line_produces_stable_hash(self):
        h1 = finding_hash("repo", 1, "sha", "file.py", None, "cat", "desc")
        h2 = finding_hash("repo", 1, "sha", "file.py", None, "cat", "desc")
        assert h1 == h2

    def test_path_normalization_produces_same_hash(self):
        h1 = finding_hash("repo", 1, "sha", "./addition.py", 10, "bug", "desc")
        h2 = finding_hash("repo", 1, "sha", "addition.py", 10, "bug", "desc")
        assert h1 == h2


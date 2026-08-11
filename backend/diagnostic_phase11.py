"""
Phase 11 Diagnostic Script — Run ONCE with real GitHub credentials.

Usage (from backend/):
    ../venv/bin/python diagnostic_phase11.py <installation_id> <owner> <repo> <pr_number>

This script:
1. Gets a real installation token (same flow as the worker)
2. Fetches actual PR files from GitHub
3. Runs get_changed_lines() on the real patch
4. Simulates a finding at file='newassition.py', line=2
5. Runs ReviewPublisher classification logic end-to-end
6. Actually posts the review to GitHub and shows the exact response

Set SIMULATE_ONLY=1 to skip posting to GitHub.
"""

import sys
import os
import json

# Make sure backend/ is on path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def main():
    if len(sys.argv) < 5:
        print("Usage: diagnostic_phase11.py <installation_id> <owner> <repo> <pr_number>")
        sys.exit(1)

    installation_id = int(sys.argv[1])
    owner           = sys.argv[2]
    repo            = sys.argv[3]
    pr_number       = int(sys.argv[4])
    simulate_only   = os.environ.get("SIMULATE_ONLY", "0") == "1"

    # -------------------------------------------------------------------------
    print("\n" + "="*70)
    print("STEP 1: Get installation token")
    print("="*70)

    from app.github.auth import get_installation_token
    token = get_installation_token(installation_id)
    print(f"Token obtained (first 8 chars): {token[:8]}...")

    # -------------------------------------------------------------------------
    print("\n" + "="*70)
    print("STEP 2: Fetch PR files from GitHub")
    print("="*70)

    from app.github.client import GitHubClient
    from app.github.diff import get_changed_lines, _normalize_path

    github = GitHubClient(token=token)
    files = github.get_pull_request_files(owner=owner, repo=repo, pr_number=pr_number)

    print(f"\nTotal files in PR: {len(files)}")
    print("\nFile details:")
    for f in files:
        fname = f.get("filename", "")
        patch = f.get("patch", "") or ""
        changed = get_changed_lines(patch)
        print(f"  filename: '{fname}'")
        print(f"  status:   {f.get('status')}")
        print(f"  patch (first 300 chars): {patch[:300]!r}")
        print(f"  changed lines: {sorted(changed)}")
        print()

    # -------------------------------------------------------------------------
    print("\n" + "="*70)
    print("STEP 3: Simulate finding at newassition.py:2")
    print("="*70)

    simulated_finding = {
        "file": "newassition.py",
        "line": 2,
        "title": "Division by zero risk",
        "severity": "HIGH",
        "category": "bug",
        "description": "The expression `a/b` can raise ZeroDivisionError if b is 0.",
        "suggestion": "Add a check: if b == 0: raise ValueError('b must not be zero')",
    }

    # Match exactly as ReviewPublisher does
    raw_file  = simulated_finding["file"]
    norm_file = _normalize_path(raw_file)
    line_num  = int(simulated_finding["line"])

    print(f"Finding: file='{raw_file}' (normalized='{norm_file}'), line={line_num}")

    changed_lines_by_file = {}
    for f in files:
        orig = f.get("filename", "")
        patch = f.get("patch", "") or ""
        lines = get_changed_lines(patch)
        changed_lines_by_file[orig] = lines
        changed_lines_by_file[_normalize_path(orig)] = lines
        print(f"  Mapping '{orig}' -> changed_lines: {sorted(lines)}")

    changed = changed_lines_by_file.get(raw_file) or changed_lines_by_file.get(norm_file) or set()
    print(f"\nChanged lines for '{norm_file}': {sorted(changed)}")
    print(f"Is line {line_num} in changed lines? {line_num in changed}")

    if line_num in changed:
        print("\nCLASSIFICATION: INLINE-ELIGIBLE ✅")
    else:
        print("\nCLASSIFICATION: SUMMARY-ONLY ❌")
        print("Reason: line not in diff changed lines")
        return

    # -------------------------------------------------------------------------
    print("\n" + "="*70)
    print("STEP 4: Build review payload")
    print("="*70)

    # Get latest commit SHA
    import requests
    pr_resp = requests.get(
        f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
    )
    pr_resp.raise_for_status()
    commit_sha = pr_resp.json()["head"]["sha"]
    print(f"commit_sha: {commit_sha}")

    # Find exact filename to use (matching GitHub's filename)
    target_path = raw_file
    for f in files:
        if _normalize_path(f.get("filename")) == norm_file:
            target_path = f.get("filename")
            break
    print(f"target_path (for GitHub): '{target_path}'")

    comment_body = (
        f"### 🤖 {simulated_finding.get('title', 'AI Finding')}\n\n"
        f"**Severity:** `{simulated_finding.get('severity')}` · "
        f"**Category:** `{simulated_finding.get('category')}`\n\n"
        f"{simulated_finding.get('description', '')}\n\n"
        f"**Suggestion:** {simulated_finding.get('suggestion', '')}\n"
    )

    summary_marker = f"<!-- ai-pr-agent:{commit_sha} -->"
    summary_body = (
        f"{summary_marker}\n"
        f"## 🤖 AI Code Review\n\n"
        f"### Found **1 issue(s)**\n\n"
        f"---\n**👀 AI Policy Decision: HUMAN_REVIEW**\n"
    )

    payload = {
        "commit_id": commit_sha,
        "body": summary_body,
        "event": "COMMENT",
        "comments": [
            {
                "path": target_path,
                "line": line_num,
                "side": "RIGHT",
                "body": comment_body,
            }
        ],
    }

    print("\nExact GitHub Review API payload:")
    print(json.dumps(payload, indent=2))

    if simulate_only:
        print("\nSIMULATE_ONLY=1 — not posting to GitHub.")
        return

    # -------------------------------------------------------------------------
    print("\n" + "="*70)
    print("STEP 5: POST to GitHub Reviews API")
    print("="*70)

    url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}/reviews"
    print(f"POST {url}")

    response = requests.post(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        json=payload,
    )

    print(f"\nHTTP Status: {response.status_code}")
    print(f"Response Body:\n{response.text}")

    if response.status_code == 200:
        review = response.json()
        print(f"\n✅ SUCCESS! GitHub Review ID: {review.get('id')}")
        print(f"   Review State: {review.get('state')}")
        print(f"   Review HREF:  {review.get('html_url')}")
    else:
        print(f"\n❌ FAILURE! GitHub returned {response.status_code}")
        try:
            err = response.json()
            print(f"   Error message: {err.get('message')}")
            print(f"   Errors: {json.dumps(err.get('errors', []), indent=4)}")
        except Exception:
            pass

if __name__ == "__main__":
    main()

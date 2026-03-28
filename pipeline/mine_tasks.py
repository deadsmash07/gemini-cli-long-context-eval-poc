#!/usr/bin/env python3
"""
Mine candidate coding tasks from GitHub pull requests.

Queries merged PRs from a given repository, filters by complexity heuristics,
and generates CodingTaskManifest JSON files suitable for the long-context
evaluation dataset.

Usage:
    export GITHUB_TOKEN=ghp_...
    python mine_tasks.py --repo tiangolo/fastapi --language python --output tasks.json
"""

import argparse
import json
import os
import sys
import time
from datetime import date
from typing import Any

import requests

API_BASE = "https://api.github.com"

# Difficulty thresholds based on files changed
DIFFICULTY_THRESHOLDS = {
    (3, 5): 2,    # L2: moderate, multi-file
    (6, 10): 3,   # L3: complex, cross-cutting
    (11, 999): 4, # L4: expert, architectural
}

TOKENS_PER_LINE = 100  # rough approximation for BPE tokenizers


def get_session(token: str | None) -> requests.Session:
    """Build a requests session with auth and standard headers."""
    session = requests.Session()
    session.headers.update({
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    })
    if token:
        session.headers["Authorization"] = f"Bearer {token}"
    return session


def check_rate_limit(response: requests.Response) -> None:
    """Sleep if we're close to hitting the GitHub API rate limit."""
    remaining = int(response.headers.get("X-RateLimit-Remaining", 999))
    if remaining < 10:
        reset_time = int(response.headers.get("X-RateLimit-Reset", 0))
        wait = max(reset_time - int(time.time()), 1)
        print(f"  Rate limit nearly exhausted ({remaining} left). "
              f"Sleeping {wait}s until reset...", file=sys.stderr)
        time.sleep(wait)


def classify_difficulty(files_changed: int) -> int:
    """Map file count to difficulty level."""
    for (lo, hi), level in DIFFICULTY_THRESHOLDS.items():
        if lo <= files_changed <= hi:
            return level
    return 2  # default for edge cases


def fetch_merged_prs(
    session: requests.Session,
    repo: str,
    language: str | None,
    per_page: int = 30,
    max_pages: int = 5,
) -> list[dict[str, Any]]:
    """Fetch merged pull requests from the GitHub search API."""
    query_parts = [f"repo:{repo}", "is:pr", "is:merged"]
    if language:
        query_parts.append(f"language:{language}")

    query = " ".join(query_parts)
    prs: list[dict[str, Any]] = []

    for page in range(1, max_pages + 1):
        url = f"{API_BASE}/search/issues"
        params = {"q": query, "sort": "updated", "order": "desc",
                  "per_page": per_page, "page": page}
        resp = session.get(url, params=params)
        resp.raise_for_status()
        check_rate_limit(resp)

        data = resp.json()
        prs.extend(data.get("items", []))

        if len(data.get("items", [])) < per_page:
            break  # no more pages

        print(f"  Fetched page {page} ({len(prs)} PRs so far)", file=sys.stderr)

    return prs


def fetch_pr_details(
    session: requests.Session, repo: str, pr_number: int
) -> dict[str, Any] | None:
    """Fetch detailed PR data including file list and merge commit info."""
    url = f"{API_BASE}/repos/{repo}/pulls/{pr_number}"
    resp = session.get(url)
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    check_rate_limit(resp)
    return resp.json()


def fetch_pr_files(
    session: requests.Session, repo: str, pr_number: int
) -> list[dict[str, Any]]:
    """Fetch the list of files changed in a PR."""
    files: list[dict[str, Any]] = []
    page = 1
    while True:
        url = f"{API_BASE}/repos/{repo}/pulls/{pr_number}/files"
        resp = session.get(url, params={"per_page": 100, "page": page})
        resp.raise_for_status()
        check_rate_limit(resp)

        batch = resp.json()
        files.extend(batch)
        if len(batch) < 100:
            break
        page += 1

    return files


def fetch_parent_sha(
    session: requests.Session, repo: str, merge_commit_sha: str
) -> str | None:
    """Get the first parent of the merge commit (the base branch state)."""
    url = f"{API_BASE}/repos/{repo}/git/commits/{merge_commit_sha}"
    resp = session.get(url)
    if resp.status_code != 200:
        return None
    check_rate_limit(resp)

    parents = resp.json().get("parents", [])
    return parents[0]["sha"] if parents else None


def build_task_manifest(
    repo: str,
    pr: dict[str, Any],
    pr_details: dict[str, Any],
    files: list[dict[str, Any]],
    parent_sha: str,
    task_index: int,
    language: str | None,
) -> dict[str, Any]:
    """Construct a CodingTaskManifest dict from PR data."""
    repo_short = repo.split("/")[-1].lower()
    pr_number = pr["number"]
    title_slug = pr["title"][:40].lower().replace(" ", "-")
    # Clean slug to match pattern ^[a-z0-9]+(-[a-z0-9]+)*$
    title_slug = "".join(c if c.isalnum() or c == "-" else "" for c in title_slug)
    title_slug = "-".join(part for part in title_slug.split("-") if part)

    task_id = f"task-{task_index:03d}-{repo_short}-{title_slug}"

    file_paths = [f["filename"] for f in files]
    total_additions = sum(f.get("additions", 0) for f in files)
    total_changes = sum(f.get("changes", 0) for f in files)
    token_estimate = total_changes * TOKENS_PER_LINE

    languages = [language] if language else ["unknown"]

    manifest: dict[str, Any] = {
        "id": task_id,
        "repo": f"https://github.com/{repo}",
        "source_pr": f"https://github.com/{repo}/pull/{pr_number}",
        "pr_title": pr["title"],
        "commit_sha": parent_sha,
        "language": languages,
        "difficulty": classify_difficulty(len(files)),
        "context_files": file_paths,
        "context_tokens_estimate": token_estimate,
        "prompt": (
            f"[AUTO-MINED] This task was mined from PR #{pr_number}: "
            f"{pr['title']}. Manual prompt curation required before use "
            f"in evaluations."
        ),
        "verification": {
            "type": "diff_match",
            "expected_files_changed": file_paths,
            "reference_diff": f"diffs/{task_id}.patch",
        },
        "metadata": {
            "tags": ["auto-mined"],
            "mined_from": f"PR #{pr_number}",
            "created_at": date.today().isoformat(),
        },
    }
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Mine coding tasks from GitHub PRs for the long-context eval dataset."
    )
    parser.add_argument("--repo", required=True, help="GitHub repo as OWNER/REPO")
    parser.add_argument("--min-files", type=int, default=3,
                        help="Minimum changed files to qualify (default: 3)")
    parser.add_argument("--max-files", type=int, default=20,
                        help="Maximum changed files to qualify (default: 20)")
    parser.add_argument("--min-additions", type=int, default=20,
                        help="Minimum added lines to qualify (default: 20)")
    parser.add_argument("--language", default="python",
                        help="Filter PRs by language (default: python)")
    parser.add_argument("--output", default="tasks.json",
                        help="Output file path (default: tasks.json)")
    args = parser.parse_args()

    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        print("Warning: GITHUB_TOKEN not set. Requests will be rate-limited.",
              file=sys.stderr)

    session = get_session(token)

    print(f"Mining tasks from {args.repo}...", file=sys.stderr)
    prs = fetch_merged_prs(session, args.repo, args.language)
    print(f"Found {len(prs)} merged PRs to evaluate.", file=sys.stderr)

    tasks: list[dict[str, Any]] = []
    task_index = 1

    for i, pr in enumerate(prs):
        pr_number = pr["number"]
        print(f"  [{i+1}/{len(prs)}] PR #{pr_number}: {pr['title'][:60]}...",
              file=sys.stderr)

        pr_details = fetch_pr_details(session, args.repo, pr_number)
        if not pr_details:
            print(f"    Skipped: could not fetch PR details.", file=sys.stderr)
            continue

        changed_files = pr_details.get("changed_files", 0)
        additions = pr_details.get("additions", 0)

        if changed_files < args.min_files or changed_files > args.max_files:
            print(f"    Skipped: {changed_files} files "
                  f"(need {args.min_files}-{args.max_files}).", file=sys.stderr)
            continue

        if additions < args.min_additions:
            print(f"    Skipped: {additions} additions "
                  f"(need >= {args.min_additions}).", file=sys.stderr)
            continue

        merge_sha = pr_details.get("merge_commit_sha")
        if not merge_sha:
            print(f"    Skipped: no merge commit SHA.", file=sys.stderr)
            continue

        parent_sha = fetch_parent_sha(session, args.repo, merge_sha)
        if not parent_sha:
            print(f"    Skipped: could not resolve parent SHA.", file=sys.stderr)
            continue

        files = fetch_pr_files(session, args.repo, pr_number)

        manifest = build_task_manifest(
            args.repo, pr, pr_details, files, parent_sha, task_index, args.language
        )
        tasks.append(manifest)
        task_index += 1
        print(f"    Added as {manifest['id']} "
              f"(difficulty={manifest['difficulty']}, "
              f"files={len(files)}, "
              f"est_tokens={manifest['context_tokens_estimate']})",
              file=sys.stderr)

    with open(args.output, "w") as f:
        json.dump(tasks, f, indent=2)

    print(f"\nWrote {len(tasks)} task manifests to {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()

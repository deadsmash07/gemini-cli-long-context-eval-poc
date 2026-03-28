#!/usr/bin/env python3
"""
Validate CodingTaskManifest files against the JSON schema.

Performs both schema validation (via jsonschema) and semantic checks
that go beyond what JSON Schema can express.

Usage:
    python validate_task.py --schema schema/task-manifest.schema.json --tasks schema/sample-tasks/
"""

import argparse
import json
import re
import sys
from pathlib import Path

from jsonschema import Draft7Validator, ValidationError

SHA_RE = re.compile(r"^[0-9a-f]{40}$")

DIFFICULTY_FILE_RANGES = {
    2: (3, 5),
    3: (6, 10),
    4: (11, 999),
}


def load_json(path: Path) -> dict | list | None:
    """Load and parse a JSON file, returning None on failure."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        print(f"  ERROR: Failed to parse {path}: {e}", file=sys.stderr)
        return None


def validate_schema(task: dict, validator: Draft7Validator, path: Path) -> list[str]:
    """Run JSON Schema validation, returning a list of error messages."""
    errors = []
    for error in sorted(validator.iter_errors(task), key=lambda e: list(e.path)):
        field = ".".join(str(p) for p in error.absolute_path) or "(root)"
        errors.append(f"  Schema: [{field}] {error.message}")
    return errors


def validate_semantics(task: dict, path: Path) -> list[str]:
    """Run semantic checks beyond JSON Schema validation."""
    warnings = []
    errors = []

    # commit_sha format
    sha = task.get("commit_sha", "")
    if sha and not SHA_RE.match(sha):
        errors.append(f"  Semantic: commit_sha is not a valid 40-char hex string: {sha}")

    # language array
    langs = task.get("language", [])
    if not langs:
        errors.append("  Semantic: language array is empty")

    # difficulty vs context_files count consistency
    difficulty = task.get("difficulty")
    context_files = task.get("context_files", [])
    n_files = len(context_files)
    if difficulty and difficulty in DIFFICULTY_FILE_RANGES:
        lo, hi = DIFFICULTY_FILE_RANGES[difficulty]
        if not (lo <= n_files <= hi):
            warnings.append(
                f"  Warning: difficulty={difficulty} typically implies "
                f"{lo}-{hi} context files, but found {n_files}"
            )

    # verification.type consistency
    verification = task.get("verification", {})
    v_type = verification.get("type", "")
    if v_type in ("test_suite", "hybrid") and not verification.get("test_command"):
        errors.append(
            f"  Semantic: verification.type={v_type} requires test_command"
        )
    if v_type in ("diff_match", "hybrid") and not verification.get("reference_diff"):
        warnings.append(
            f"  Warning: verification.type={v_type} should include reference_diff"
        )

    return errors + warnings


def validate_file(path: Path, validator: Draft7Validator) -> bool:
    """Validate a single task manifest file. Returns True if valid."""
    print(f"Validating {path.name}...")
    task = load_json(path)
    if task is None:
        return False

    schema_errors = validate_schema(task, validator, path)
    semantic_issues = validate_semantics(task, path)

    all_issues = schema_errors + semantic_issues
    if all_issues:
        for issue in all_issues:
            print(issue, file=sys.stderr)

    # Separate hard errors from warnings
    hard_errors = [i for i in all_issues if not i.strip().startswith("Warning:")]
    if hard_errors:
        print(f"  FAILED ({len(hard_errors)} error(s))\n", file=sys.stderr)
        return False

    warnings = [i for i in all_issues if i.strip().startswith("Warning:")]
    if warnings:
        print(f"  PASSED with {len(warnings)} warning(s)\n")
    else:
        print(f"  PASSED\n")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate CodingTaskManifest files against the JSON schema."
    )
    parser.add_argument("--schema", required=True, help="Path to the JSON schema file")
    parser.add_argument("--tasks", required=True,
                        help="Path to a task JSON file or a directory of task files")
    args = parser.parse_args()

    schema_path = Path(args.schema)
    schema = load_json(schema_path)
    if schema is None:
        print(f"Could not load schema from {schema_path}", file=sys.stderr)
        sys.exit(1)

    validator = Draft7Validator(schema)

    tasks_path = Path(args.tasks)
    if tasks_path.is_dir():
        task_files = sorted(tasks_path.glob("*.json"))
    elif tasks_path.is_file():
        task_files = [tasks_path]
    else:
        print(f"Path not found: {tasks_path}", file=sys.stderr)
        sys.exit(1)

    if not task_files:
        print("No JSON files found to validate.", file=sys.stderr)
        sys.exit(1)

    total = len(task_files)
    passed = sum(1 for f in task_files if validate_file(f, validator))
    failed = total - passed

    print(f"Results: {passed}/{total} passed, {failed} failed")
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()

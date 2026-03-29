Your team needs a tool that automatically generates Git hooks for projects to enforce code quality standards. Build an executable at /usr/local/bin/hook-gen that reads configuration from /app/input/hook-config.json, detects the project type by examining /app/project/, generates appropriate hook scripts in /app/output/hooks/, and creates a summary report at /app/output/hook-report.json.

The configuration specifies which quality checks (linting, testing, commit format validation) should run and at which Git hook stages (pre-commit vs pre-push). Your tool must auto-detect whether the project is Python or JavaScript by examining dependency files (requirements.txt/setup.py for Python, package.json for JavaScript), then generate hook scripts that invoke the appropriate tools for that ecosystem.

For pre-commit hooks, check only staged files to keep commits fast. For pre-push hooks, validate all modified files since this runs less frequently. Generated hooks should exit with non-zero status when checks fail to block the Git operation, and provide clear error messages to help developers fix issues.

Input config structure (/app/input/hook-config.json):
{
  "linting": {"enabled": bool, "pre_commit": bool, "pre_push": bool},
  "testing": {"enabled": bool, "pre_commit": bool, "pre_push": bool},
  "commit_format": {"enabled": bool, "pre_commit": bool, "pre_push": bool}
}

Output JSON structure (/app/output/hook-report.json):
{
  "project_type": "python" or "javascript",
  "project_path": "/app/project",
  "hooks_generated": [
    {
      "hook_name": "pre-commit" or "pre-push",
      "hook_path": "/app/output/hooks/pre-commit",
      "checks_enabled": ["linting", "testing", "commit_format"],
      "executable": true
    }
  ],
  "checks_configured": {
    "linting": {
      "enabled": bool,
      "tool": "ruff"|"flake8" (Python) or "eslint" (JavaScript),
      "hooks": ["pre-commit", "pre-push"]
    },
    "testing": {
      "enabled": bool,
      "command": "pytest" (Python) or "npm test" (JavaScript),
      "hooks": ["pre-commit", "pre-push"]
    },
    "commit_format": {
      "enabled": bool,
      "standard": "conventional-commits",
      "hooks": ["pre-commit", "pre-push"]
    }
  }
}

Important field requirements:
-> Sort hooks_generated array by hook_name alphabetically
-> Sort checks_enabled arrays alphabetically within each hook entry
-> The checks_enabled array must list only the checks that are both enabled AND configured for that specific hook (example, if linting is enabled with pre_commit=true, include "linting" in pre-commit hook's checks_enabled)

Generated hook script requirements:
-> Must be executable with proper shebang (#!/bin/bash or #!/usr/bin/env bash)
-> Must include explicit "exit 1" statements in error handling paths to block Git operations on failure
-> Error messages must use "Error:" prefix format (e.g., "Error: Linting failed")
-> Must exit with non-zero status when any check fails

# Architecture: Long-Context Coding Eval Integration

## Overview

This document describes how the long-context coding evaluation dataset
integrates with Gemini CLI's existing eval infrastructure. The design
principle is extension, not replacement: the coding eval system wraps and
reuses the existing `TestRig`, `evalTest()`, and aggregation patterns rather
than introducing parallel infrastructure.

---

## Existing Gemini CLI Eval Architecture

The current eval system in `google/gemini-cli` is structured as follows:

```
evals/
├── *.eval.ts              # 19 behavioral eval files
├── test-helper.ts         # evalTest() function, EvalCase interface
├── app-test-helper.ts     # AppRig-based evals (in-process execution)
├── vitest.config.ts       # 5-minute timeout, JSON reporter
└── logs/                  # Activity logs in JSONL format

packages/test-utils/
└── src/test-rig.ts        # TestRig class: setup, run, readToolLogs, cleanup

scripts/
└── aggregate_evals.js     # Nightly results aggregation

.github/workflows/
├── evals-nightly.yml      # Runs USUALLY_PASSES evals 3x across model matrix
└── chained_e2e.yml        # Runs ALWAYS_PASSES evals in every CI run
```

**Key abstractions in the existing system:**

- **`EvalCase`** -- Interface defining a single eval: prompt, expected
  behavior, pass criteria, and eval policy (`ALWAYS_PASSES` or
  `USUALLY_PASSES`).

- **`evalTest()`** -- Test wrapper that handles retry logic based on eval
  policy. `ALWAYS_PASSES` evals run once and must pass. `USUALLY_PASSES`
  evals run up to 3 times and pass if they succeed at least once.

- **`TestRig`** -- Sets up an isolated environment, runs the agent with a
  given prompt, collects activity logs (tool calls, model responses), and
  provides `readToolLogs()` for assertions against agent behavior.

- **Activity logs** -- JSONL files recording every tool call, model
  response, and intermediate state during an eval run. These are the
  primary data source for understanding agent behavior.

---

## Proposed Addition: Coding Task Eval System

### Directory Structure

```
evals/coding-tasks/
├── manifests/                  # CodingTaskManifest JSON files (30-50 tasks)
│   ├── fastapi-fix-001.json
│   ├── ruff-refactor-012.json
│   └── ...
├── coding-task-runner.ts       # CodingTaskRunner: wraps TestRig
├── coding-task-runner.test.ts  # Unit tests for the runner itself
├── vitest.config.ts            # Extended timeouts (15-30 min per task)
└── logs/                       # Per-task activity logs (JSONL)

pipeline/
├── mine_tasks.py               # PR mining: GitHub API -> candidate tasks
├── validate_task.py            # Schema validation for manifests
└── analyze_activity_log.ts     # Activity log -> behavioral metrics

scripts/
└── aggregate_coding_evals.js   # Extends existing aggregation pattern

.github/workflows/
└── coding-evals-weekly.yml     # Weekly run across model matrix
```

### CodingTaskManifest Schema

Each task is defined by a JSON manifest (see `schema/coding-task-manifest.schema.json`
for the full JSON Schema). The key fields:

```
{
  "task_id":          "fastapi-fix-001",
  "repo_url":         "https://github.com/tiangolo/fastapi",
  "commit_sha":       "abc123...",
  "difficulty":       2,
  "language":         "python",
  "domain":           "web-framework",
  "prompt":           "The /items/{item_id} endpoint returns 500...",
  "files_in_scope":   ["fastapi/routing.py", "tests/test_routing.py"],
  "verification": {
    "type":           "test_suite",
    "test_command":   "pytest tests/test_routing.py -x",
    "expected_exit":  0
  },
  "ground_truth_patch": "diff --git a/...",
  "metadata": {
    "source_pr":      "https://github.com/tiangolo/fastapi/pull/1234",
    "lines_changed":  12,
    "files_changed":  2,
    "estimated_tool_calls": 8
  }
}
```

---

## How CodingTaskRunner Extends TestRig

`CodingTaskRunner` is not a fork of `TestRig` -- it is a wrapper that
delegates to `TestRig` for agent execution and log collection, while adding
the repo-setup and verification layers that coding tasks require.

```
┌─────────────────────────────────────────────────────┐
│                  CodingTaskRunner                    │
│                                                     │
│  ┌───────────────┐   ┌───────────────────────────┐  │
│  │  Repo Setup   │   │      Verification         │  │
│  │               │   │                           │  │
│  │ - git clone   │   │ - run test_command        │  │
│  │ - checkout SHA│   │ - check exit code         │  │
│  │ - install deps│   │ - diff match (optional)   │  │
│  │ - validate    │   │ - collect coverage delta  │  │
│  └───────┬───────┘   └───────────┬───────────────┘  │
│          │                       │                   │
│          ▼                       ▲                   │
│  ┌───────────────────────────────────────────────┐   │
│  │              TestRig (existing)                │   │
│  │                                               │   │
│  │  - setup isolated environment                 │   │
│  │  - run agent with prompt                      │   │
│  │  - collect activity logs (JSONL)              │   │
│  │  - readToolLogs() for assertions              │   │
│  │  - cleanup                                    │   │
│  └───────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────┘
```

**What CodingTaskRunner adds on top of TestRig:**

| Responsibility | TestRig (existing) | CodingTaskRunner (new) |
|---|---|---|
| Environment setup | Creates temp directory, sets env vars | Clones repo at pinned SHA, installs dependencies |
| Agent execution | Runs agent with prompt, streams tool calls | Passes manifest prompt to TestRig, sets working directory to cloned repo |
| Log collection | Writes JSONL activity log | Reads TestRig logs + adds task-level metadata (difficulty, language, domain) |
| Verification | Checks agent output against expected | Runs test suite or diff match against ground truth patch |
| Cleanup | Removes temp directory | Removes cloned repo + TestRig cleanup |
| Timeout | 5 minutes (vitest default) | 15-30 minutes (configurable per difficulty level) |

---

## End-to-End Flow

```
                    ┌──────────────────┐
                    │   Task Manifest  │
                    │   (JSON file)    │
                    └────────┬─────────┘
                             │
                             ▼
               ┌─────────────────────────────┐
               │   1. CodingTaskRunner.setup  │
               │                              │
               │   - Parse manifest           │
               │   - git clone <repo_url>     │
               │   - git checkout <sha>       │
               │   - Install dependencies     │
               │   - Validate build succeeds  │
               └──────────────┬──────────────┘
                              │
                              ▼
               ┌─────────────────────────────┐
               │   2. TestRig.run(prompt)     │
               │                              │
               │   Agent receives prompt:     │
               │   - Bug description / task   │
               │   - Working directory is the │
               │     cloned repo              │
               │                              │
               │   Agent uses tools:          │
               │   - grep / find / read       │
               │   - edit files               │
               │   - run commands             │
               │                              │
               │   All tool calls logged to   │
               │   activity log (JSONL)       │
               └──────────────┬──────────────┘
                              │
                              ▼
               ┌─────────────────────────────┐
               │   3. CodingTaskRunner.verify │
               │                              │
               │   Verification strategy      │
               │   (from manifest):           │
               │                              │
               │   TEST_SUITE:                │
               │     Run test_command          │
               │     Check exit code == 0     │
               │                              │
               │   DIFF_MATCH:                │
               │     Compare agent's changes  │
               │     to ground_truth_patch    │
               │     (semantic diff, not      │
               │     exact string match)      │
               │                              │
               │   HYBRID:                    │
               │     Tests pass AND key       │
               │     files were modified      │
               └──────────────┬──────────────┘
                              │
                              ▼
               ┌─────────────────────────────┐
               │   4. Results & Aggregation   │
               │                              │
               │   Per-task output:           │
               │   - pass / fail              │
               │   - tool call count          │
               │   - wall-clock time          │
               │   - token usage              │
               │   - activity log path        │
               │                              │
               │   Aggregation:               │
               │   - Pass rate by difficulty  │
               │   - Pass rate by language    │
               │   - Pass rate by domain      │
               │   - Tool efficiency metrics  │
               │   - Comparison across models │
               └─────────────────────────────┘
```

---

## Integration Points with Existing Infrastructure

### 1. evalTest() Compatibility

Coding tasks use the same `evalTest()` wrapper as existing behavioral evals.
Each task maps to an eval policy:

- L1 tasks -> `ALWAYS_PASSES` (run in `chained_e2e.yml`, must pass every time)
- L2-L4 tasks -> `USUALLY_PASSES` (run in `coding-evals-weekly.yml`, pass
  rate tracked over time)

This means coding eval results appear in the same aggregation reports as
existing evals, enabling direct comparison.

### 2. Activity Log Format

Coding task activity logs use the same JSONL format as existing evals. The
`analyze_activity_log.ts` script reads these logs and extracts coding-specific
metrics:

- **Tool call sequence** -- ordered list of tools invoked, with arguments
  and timestamps.
- **Search-to-edit ratio** -- proportion of tool calls spent reading/searching
  vs. editing. High ratios indicate the agent struggled to locate the
  relevant code.
- **Backtrack count** -- number of times the agent edited a file, then
  edited it again (indicating a wrong first attempt).
- **Context window utilization** -- how much of the available context was
  used across all tool calls.

### 3. Aggregation

`aggregate_coding_evals.js` extends the pattern in the existing
`aggregate_evals.js`. It reads per-task JSON results and produces:

- Summary tables sliced by difficulty level, language, and domain.
- Comparison matrices across models in the model matrix.
- Trend data for tracking model improvement over time.

The output format is compatible with the existing nightly report structure
so that coding eval results can be included in the same dashboard.

### 4. CI Workflow

```yaml
# .github/workflows/coding-evals-weekly.yml
#
# Runs coding evals weekly (Sunday 02:00 UTC).
# Runs each USUALLY_PASSES task 3x across the model matrix.
# L1 (ALWAYS_PASSES) tasks run in chained_e2e.yml instead.

name: Coding Evals (Weekly)
on:
  schedule:
    - cron: '0 2 * * 0'
  workflow_dispatch:

jobs:
  coding-evals:
    strategy:
      matrix:
        model: [gemini-2.5-pro, gemini-2.5-flash]
    runs-on: ubuntu-latest
    timeout-minutes: 180
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
      - run: npm ci
      - run: npx vitest run --config evals/coding-tasks/vitest.config.ts
        env:
          GEMINI_MODEL: ${{ matrix.model }}
      - uses: actions/upload-artifact@v4
        with:
          name: coding-eval-results-${{ matrix.model }}
          path: evals/coding-tasks/logs/
```

---

## Pipeline: From PR to Task Manifest

The mining pipeline converts merged PRs into validated task manifests:

```
GitHub API             mine_tasks.py          validate_task.py
    │                      │                       │
    │  merged PRs          │  candidate tasks      │  validated manifests
    │  (last 12 months)    │  (JSON)               │  (JSON)
    ▼                      ▼                       ▼
┌────────┐  query   ┌────────────┐  filter   ┌──────────────┐
│ GitHub │ -------> │   Mining   │ -------> │  Validation  │
│  API   │          │   Script   │          │   Script     │
└────────┘          └────────────┘          └──────────────┘
                         │                       │
                         │ filters:              │ checks:
                         │ - patch size          │ - schema conformance
                         │ - test presence       │ - repo builds at SHA
                         │ - file count          │ - tests pass at SHA
                         │ - no merge conflicts  │ - tests fail pre-patch
                         │ - linked issue exists │ - tests pass post-patch
                         │                       │ - contamination check
                         ▼                       ▼
                    candidates/             manifests/
                    (staging)               (production)
```

**Mining filters** (in `mine_tasks.py`):

- Patch touches 1-20 files (too many files = too noisy).
- At least one test file is modified or added.
- The PR has a linked issue or descriptive body (needed to generate the
  task prompt).
- No merge conflicts in the PR's history.
- The patch applies cleanly to the base commit.

**Validation checks** (in `validate_task.py`):

- Manifest conforms to `coding-task-manifest.schema.json`.
- Repository clones and builds at the pinned commit SHA.
- Test suite passes at the pinned commit (pre-patch baseline).
- Test suite fails when the relevant test is run against the pre-patch code
  (confirms the test actually covers the bug).
- Test suite passes after applying the ground truth patch.
- Contamination verification protocol passes.

---

## Timeout Strategy

Coding tasks require significantly longer timeouts than behavioral evals.
The timeout scales with difficulty level:

| Difficulty | Timeout | Rationale |
|---|---|---|
| L1 | 5 min | Same as existing evals; localized tasks complete quickly |
| L2 | 10 min | Cross-file navigation adds overhead |
| L3 | 20 min | Architectural investigation requires extended search |
| L4 | 30 min | Multi-step reasoning with trial-and-error |

These timeouts are enforced at the vitest level via per-test configuration
in `coding-task-runner.ts`, overriding the default 5-minute timeout in the
base `vitest.config.ts`.

---

## Data Flow Summary

```
                   Mining Pipeline
                   (offline, runs on demand)
                          │
                          ▼
┌──────────────────────────────────────────────┐
│              manifests/*.json                 │
│  (30-50 validated task manifests)             │
└──────────────────────┬───────────────────────┘
                       │
          ┌────────────┼────────────┐
          │            │            │
          ▼            ▼            ▼
     CI weekly    CI per-push    Local dev
     (L2-L4)     (L1 only)     (any task)
          │            │            │
          └────────────┼────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────┐
│           CodingTaskRunner                    │
│  setup -> TestRig.run -> verify -> report     │
└──────────────────────┬───────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────┐
│           logs/*.jsonl                        │
│  (activity logs + per-task results)           │
└──────────────────────┬───────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────┐
│     aggregate_coding_evals.js                 │
│  (summary tables, model comparisons, trends)  │
└──────────────────────────────────────────────┘
```

---

## Open Design Questions

These items require further investigation or discussion before
implementation:

1. **Dependency installation caching.** Cloning and installing dependencies
   for each task on every eval run is expensive. Should we pre-build Docker
   images per repo, or use a shared cache across tasks from the same repo?

2. **Semantic diff matching.** Exact string matching on patches is too
   brittle (whitespace, variable names, comment changes). What level of
   semantic equivalence should count as a pass? Options: AST-level diff,
   test-suite-only verification, or a hybrid.

3. **Prompt engineering for task descriptions.** The prompt the agent
   receives is derived from the PR description and issue body. How much
   should we editorialize? Verbatim PR descriptions may leak the solution;
   too-abstract descriptions may be unsolvable.

4. **Cost budget.** L4 tasks with 40+ tool calls and 30-minute timeouts
   consume significant API tokens. What is the acceptable per-run cost
   ceiling for the weekly eval suite?

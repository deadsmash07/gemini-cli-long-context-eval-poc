# Long-Context Coding Evaluation Dataset — Proof of Concept

A proof-of-concept for [GSoC 2026 Issue #23316](https://github.com/google-gemini/gemini-cli/issues/23316): building a benchmark dataset of complex, multi-file coding tasks that evaluate Gemini CLI's long-context reasoning capabilities.

## Motivation

Gemini CLI has [behavioral evals](https://github.com/google-gemini/gemini-cli/tree/main/evals) that test whether the agent picks the right tool or delegates correctly. These are useful but small — the file setups are synthetic and rarely span more than a few files. SWE-bench tests bigger tasks, but it runs in its own Docker container, disconnected from the eval infrastructure the team actually uses day to day.

What's missing is something in between: real multi-file coding tasks that run inside Gemini CLI's own tool and eval pipeline. Tasks where you need to read 5-10 files, trace dependencies, and produce a coordinated fix. That's what this project builds — 30-50 tasks mined from real OSS pull requests, integrated with the existing `TestRig` and `evalTest()` infrastructure.

## Quick Start

```bash
npm install
npm run demo        # ← works out of the box (validate + stats)
npm run eval        # Dry-run eval (validates setup, computes static metrics)
npm run stats       # Print dataset summary table
npm run validate    # Validate task manifests (needs python3 + jsonschema)
npm run eval:api    # Run evals via Gemini API (needs GEMINI_API_KEY in .env)
npm run eval:live   # Run evals against real Gemini CLI (needs gemini binary)
npm run mine        # Mine tasks from GitHub (needs GITHUB_TOKEN + requests)
```

`npm run demo` and `npm run eval` work with just Node.js. The other commands need external dependencies as noted.

## Live Evaluation Results

Ran 3 L2 tasks against the Gemini REST API (March 2026):

| Task | 2.5-flash | 2.5-pro | 3-pro | 3.1-pro |
|------|-----------|---------|-------|---------|
| task-002 (Express, L2) | **2/2 (100%)** 25s | **2/2 (100%)** 45s | **2/2 (100%)** 55s | **2/2 (100%)** 54s |
| task-004 (Flask, L2) | **4/4 (100%)** 33s | 2/4 (50%) 64s | 3/4 (75%) 63s | 3/4 (75%) 69s |
| task-001 (FastAPI, L2) | 1/4 (25%) 33s | 0/4 (0%) 63s | 0/4 (0%) 70s | 0/4 (0%) 68s |
| **Average** | **75%** | 50% | 58% | 58% |

Some observations from these runs:

- **All 4 models got the Express task right** — it had full context (3/3 files readable) and a clear bug description. Straightforward L2 task.
- **Flash outperformed Pro models on file identification.** Pro responses are more verbose and describe changes abstractly rather than naming file paths, which our parser misses. This points to a real challenge in eval design: how you parse model output matters as much as what the model says.
- **The FastAPI task was hard for everyone.** 2 of its 4 context files don't exist at the pinned SHA (they were created by the PR itself). All Pro models scored 0%. This is the kind of task design subtlety the dataset is built to catch — tasks where pre-PR state doesn't contain the test files need different verification strategies.

## What's in This POC

```
schema/
  task-manifest.schema.json        # JSON Schema for CodingTaskManifest
  sample-tasks/                    # 8 real tasks mined from OSS repos

runner/
  coding-task-runner.ts            # CodingTaskRunner — clones repos, runs agent, verifies
  metrics.ts                       # RFS, PES, CCS, TER metric implementations
  failure-taxonomy.ts              # 7-mode failure classification
  run-eval.ts                      # CLI entry point (dry-run and live modes)
  stats.ts                         # Dataset summary statistics

pipeline/
  mine_tasks.py                    # PR mining script (GitHub API)
  validate_task.py                 # Schema + semantic validation
  analyze_activity_log.ts          # Activity log -> eval metrics

eval-integration/
  coding-task.eval.ts              # Demo eval using existing TestRig + evalTest()
  vitest.config.ts                 # Extended timeout config

docs/
  difficulty-taxonomy.md           # 4-level task difficulty framework
  repo-selection-criteria.md       # Repository curation methodology
  architecture.md                  # Integration with Gemini CLI eval infra
```

## Evaluation Metrics

Four metrics measure agent performance on each task:

| Metric | Formula | What It Measures |
|--------|---------|-----------------|
| **RFS** (Reasoning Forcing Score) | `(context_files - changed_files) * cross_ref_weight + dep_depth` | How much cross-component reasoning the task demands |
| **PES** (Path Efficiency Score) | `relevant_files_read / total_files_read` | How efficiently the agent navigated to the solution |
| **CCS** (Context Coverage Score) | `context_files_read / total_context_files` | What fraction of required context the agent consumed |
| **TER** (Tool Efficiency Ratio) | `(edits + targeted_reads) / total_tool_calls` | Ratio of productive tool calls to total |

## Failure Taxonomy

When a task fails, the runner classifies the failure into one of 7 modes:

| Mode | Description |
|------|-------------|
| `context_insufficient` | Agent didn't read enough context files |
| `wrong_files_targeted` | Agent edited files not in the expected change set |
| `shallow_fix` | Minimal change that doesn't address root cause |
| `cross_component_miss` | Fixed one file but missed related changes |
| `test_regression` | Fix introduced new test failures |
| `timeout` | Agent exceeded time limit |
| `complete_hallucination` | Changes unrelated to the task |

## Task Difficulty Taxonomy

| Level | Name | Files | Context | Eval Policy |
|-------|------|-------|---------|-------------|
| L1 | Localized | 1 | <500 lines | `ALWAYS_PASSES` |
| L2 | Cross-file | 2-5 | 500-3K lines | `ALWAYS_PASSES` / `USUALLY_PASSES` |
| L3 | Architectural | 5-15 | 3K-15K lines | `USUALLY_PASSES` |
| L4 | Multi-step Reasoning | 10+ | 15K+ lines | `USUALLY_PASSES` |

See [docs/difficulty-taxonomy.md](docs/difficulty-taxonomy.md) for the full framework.

## CodingTaskRunner

The `CodingTaskRunner` is the core eval runner. It wraps Gemini CLI's existing `TestRig` pattern:

1. **Setup**: Clones the target repo (bare clone cache at `~/.cache/coding-task-evals/repos/`), creates an isolated git worktree at the pinned `commit_sha`
2. **Execute**: Spawns Gemini CLI with the task prompt, captures activity log via `GEMINI_CLI_ACTIVITY_LOG_TARGET`
3. **Verify**: Runs the task's verification (test suite execution or diff comparison)
4. **Analyze**: Computes RFS, PES, CCS, TER metrics from the activity log
5. **Classify**: If failed, classifies failure mode into the 7-mode taxonomy

```typescript
const runner = new CodingTaskRunner(manifest, {
  cacheDir: '~/.cache/coding-task-evals/repos/',
  timeout: 900000, // 15 minutes
});
const result = await runner.run();
// result.metrics: { rfs, pes, ccs, ter }
// result.failure?: { mode, confidence, evidence }
```

## Integration with Gemini CLI

This dataset integrates with Gemini CLI's **existing** eval infrastructure:

- Tasks defined as `CodingTaskManifest` JSON files — extending the [`EvalCase`](https://github.com/google-gemini/gemini-cli/blob/main/evals/test-helper.ts#L199-L207) interface pattern
- Runner wraps [`TestRig`](https://github.com/google-gemini/gemini-cli/blob/main/packages/test-utils/src/test-rig.ts) for execution, tool call logging, and cleanup
- Results feed into the existing [`aggregate_evals.js`](https://github.com/google-gemini/gemini-cli/blob/main/scripts/aggregate_evals.js) aggregation pattern
- Eval policies (`ALWAYS_PASSES` / `USUALLY_PASSES`) map to difficulty levels
- Activity logs use the same JSONL format via `GEMINI_CLI_ACTIVITY_LOG_TARGET`

See [docs/architecture.md](docs/architecture.md) for the full integration design.

## Sample Tasks

All 8 tasks are mined from **real merged PRs** (2024-2026 commits for contamination resistance):

| Task | Repo | Lang | Diff | Description |
|------|------|------|------|-------------|
| 001 | FastAPI | Python | L2 | Escape Swagger UI config to prevent XSS injection |
| 002 | Express | JS | L2 | Fix `app.render(view, null, cb)` TypeError regression |
| 003 | Flask | Python | L3 | Ensure all teardown callbacks run despite errors |
| 004 | Flask | Python | L2 | Add TRUSTED_HOSTS config for host header validation |
| 005 | Astro | TS | L2 | Fix `.meta` stripped from top-level Zod schema |
| 006 | Deno | TS+Rust | L3 | Skip Node-to-Deno arg translation in standalone binaries |
| 007 | Ruff | Rust | L2 | Fix UP008 false positive on nested class `super()` |
| 008 | Ruff | Rust | L3 | Fix W391 panic on consecutive empty Jupyter cells |

## Pipeline

### Mine tasks from a repository

```bash
export GITHUB_TOKEN=ghp_...
python pipeline/mine_tasks.py --repo tiangolo/fastapi --language python --min-files 3 --output tasks.json
```

### Validate task manifests

```bash
npm run validate
# or: python pipeline/validate_task.py --schema schema/task-manifest.schema.json --tasks schema/sample-tasks/
```

### Analyze activity logs

```bash
npx tsx pipeline/analyze_activity_log.ts --logs-dir evals/logs/ --manifests schema/sample-tasks/ --output report.json
```

## Related

- [Gemini CLI Evals README](https://github.com/google-gemini/gemini-cli/blob/main/evals/README.md)
- [GSoC 2026 Issue #23316](https://github.com/google-gemini/gemini-cli/issues/23316)

## License

Apache-2.0

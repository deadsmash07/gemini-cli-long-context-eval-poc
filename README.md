# Long-Context Coding Evaluation Dataset — Proof of Concept

A proof-of-concept for [GSoC 2026 Issue #23316](https://github.com/google-gemini/gemini-cli/issues/23316): building a benchmark dataset of complex, multi-file coding tasks that evaluate Gemini CLI's long-context reasoning capabilities.

## Motivation

Gemini CLI's [behavioral evals](https://github.com/google-gemini/gemini-cli/tree/main/evals) test individual agent behaviors (tool selection, delegation, memory) using small, synthetic file setups. Industry benchmarks like SWE-bench measure general capabilities but run outside Gemini CLI's tool infrastructure.

**The gap**: no evaluation dataset measures how well Gemini CLI leverages its 1M+ token context window for real-world, multi-file coding tasks — tasks that require reading across files, tracing dependencies, and implementing changes that span module boundaries.

This project fills that gap by creating 30-50 curated coding tasks mined from real open-source PRs, integrated into Gemini CLI's existing Vitest-based eval pipeline.

## What's in This POC

```
schema/
  task-manifest.schema.json        # JSON Schema for CodingTaskManifest
  sample-tasks/                    # 8 real tasks mined from OSS repos
    task-001-fastapi-*.json        #   FastAPI (Python, L2)
    task-002-express-*.json        #   Express (JavaScript, L2)
    task-003-flask-*.json          #   Flask (Python, L3)
    task-004-flask-*.json          #   Flask (Python, L2)
    task-005-astro-*.json          #   Astro (TypeScript, L2)
    task-006-deno-*.json           #   Deno (TypeScript+Rust, L3)
    task-007-ruff-*.json           #   Ruff (Rust, L2)
    task-008-ruff-*.json           #   Ruff (Rust, L3)

pipeline/
  mine_tasks.py                    # PR mining script (GitHub API)
  validate_task.py                 # Schema + semantic validation
  analyze_activity_log.ts          # Activity log -> eval metrics

eval-integration/
  coding-task.eval.ts              # Demo eval using existing TestRig
  vitest.config.ts                 # Extended timeout config

docs/
  difficulty-taxonomy.md           # 4-level task difficulty framework
  repo-selection-criteria.md       # Repository curation methodology
  architecture.md                  # Integration with Gemini CLI eval infra
```

## Task Difficulty Taxonomy

Tasks are classified into 4 difficulty levels based on the scope of reasoning required:

| Level | Name | Files | Context | Eval Policy |
|-------|------|-------|---------|-------------|
| L1 | Localized | 1 | <500 lines | `ALWAYS_PASSES` |
| L2 | Cross-file | 2-5 | 500-3K lines | `ALWAYS_PASSES` / `USUALLY_PASSES` |
| L3 | Architectural | 5-15 | 3K-15K lines | `USUALLY_PASSES` |
| L4 | Multi-step Reasoning | 10+ | 15K+ lines | `USUALLY_PASSES` |

See [docs/difficulty-taxonomy.md](docs/difficulty-taxonomy.md) for the full framework, including the connection to research on hierarchical reasoning in LLMs.

## Integration with Gemini CLI

The key design decision: this dataset integrates with Gemini CLI's **existing** eval infrastructure rather than building a standalone system.

- Tasks are defined as `CodingTaskManifest` JSON files — an extension of the existing [`EvalCase`](https://github.com/google-gemini/gemini-cli/blob/main/evals/test-helper.ts#L199-L207) interface pattern
- The eval runner uses [`TestRig`](https://github.com/google-gemini/gemini-cli/blob/main/packages/test-utils/src/test-rig.ts) for test execution, tool call logging, and cleanup
- Results feed into the existing [`aggregate_evals.js`](https://github.com/google-gemini/gemini-cli/blob/main/scripts/aggregate_evals.js) aggregation pattern
- Eval policies (`ALWAYS_PASSES` / `USUALLY_PASSES`) map directly to difficulty levels
- Activity logs use the same JSONL format via `GEMINI_CLI_ACTIVITY_LOG_TARGET`

See [docs/architecture.md](docs/architecture.md) for the full integration design.

## Sample Tasks

All 8 sample tasks are mined from **real merged PRs** in popular open-source repositories (2024-2026 commits for contamination resistance):

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

## Running the Pipeline

### Mine tasks from a repository

```bash
export GITHUB_TOKEN=ghp_...
python pipeline/mine_tasks.py \
  --repo tiangolo/fastapi \
  --language python \
  --min-files 3 \
  --output tasks.json
```

### Validate task manifests

```bash
python pipeline/validate_task.py \
  --schema schema/task-manifest.schema.json \
  --tasks schema/sample-tasks/
```

### Analyze activity logs

```bash
npx tsx pipeline/analyze_activity_log.ts \
  --logs-dir evals/logs/ \
  --manifests schema/sample-tasks/ \
  --output report.json
```

## Demo Eval

The [eval-integration/coding-task.eval.ts](eval-integration/coding-task.eval.ts) file demonstrates how a Level 2 coding task integrates with Gemini CLI's `evalTest()` + `TestRig` pattern. It sets up a realistic 10-file Express/TypeScript project with a subtle auth middleware bug (context propagation via `Object.assign` copy instead of direct mutation) and asserts that the agent correctly identifies and fixes it.

## Related

- [Gemini CLI Evals README](https://github.com/google-gemini/gemini-cli/blob/main/evals/README.md)
- [GSoC 2026 Issue #23316](https://github.com/google-gemini/gemini-cli/issues/23316)

## License

Apache-2.0

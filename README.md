# Long-Context Coding Evaluation Dataset

POC for [GSoC 2026 Issue #23316](https://github.com/google-gemini/gemini-cli/issues/23316) - a benchmark dataset of multi-file coding tasks that test Gemini CLI's long-context reasoning.

## Quick start

```bash
npm install
npm run demo          # validate all tasks + print dataset stats (works out of the box)
npm run eval          # dry-run eval with static metrics
npm run eval:api      # run Tier 1 tasks against Gemini API (needs GEMINI_API_KEY in .env)
npm run eval:challenge # run Tier 2 tasks in Docker (needs Docker)
npm run stats         # dataset summary table
```

## Results

### Tier 1: PR-mined tasks (file identification accuracy, single-turn API)

| Task | 2.5-flash | 2.5-pro | 3-pro | 3.1-pro |
|------|-----------|---------|-------|---------|
| task-002 (Express, L2) | **2/2** | **2/2** | **2/2** | **2/2** |
| task-004 (Flask, L2) | **4/4** | 2/4 | 3/4 | 3/4 |
| task-001 (FastAPI, L2)\* | 1/4 | 0/4 | 0/4 | 0/4 |
| **Average** | **75%** | 50% | 58% | 58% |

\*task-001 has a known design issue: 2 context files don't exist at the pinned SHA.

### Tier 2: Challenge tasks (Docker-containerized, Modal cloud, pytest verification)

| Task | Difficulty | 2.5-flash | 3-pro | 3.1-pro |
|------|-----------|-----------|-------|---------|
| build-queue-coordinator | Medium | 0% | - | - |
| ci-pipeline-scheduler | Hard | 0% | - | - |
| cicd-secrets-leak-scanner | Hard | 1/30 (3%) | - | - |
| compose-guard | Hard | 0/6 (0%) | - | - |
| container-image-security-audit | Hard | 0/26 (0%) | - | - |
| cron-guard | Hard | 1/10 (10%) | - | - |
| git-hook-generator | Medium | 0/31 (0%) | 1/31 (3%) | 1/31 (3%) |

**0 out of 7 tasks fully solved by any model.** Best result: cron-guard at 10% with Flash.

## Two-tier dataset

| | Tier 1: PR-mined | Tier 2: Challenge |
|---|---|---|
| Source | Real merged pull requests | Expert-designed challenges |
| Count | 11 tasks across 7 repos | 7 tasks |
| Difficulty | L2-L3 | L3-L4 |
| Languages | Python, JS, TS, Rust | Python |
| Repos | FastAPI, Express, Flask, Astro, Deno, Ruff, **gemini-cli** | Self-contained |
| Verification | Repo test suite + gold patches | Docker + pytest |
| Contamination | SHA-pinned, post-cutoff | Zero (original tasks) |
| Test code | Varies | ~2,700 lines |
| Gold patches | 11/11 | N/A |

Automated mining gives ecological validity. Hand-crafted tasks give difficulty control and zero contamination risk.

## Repository structure

```
schema/
  task-manifest.schema.json          # JSON Schema for task manifests
  sample-tasks/                      # 8 PR-mined tasks (Tier 1)

challenge-tasks/                     # 7 Docker-containerized tasks (Tier 2)
  build-queue-coordinator/           #   build queue with preemption + deps (medium)
  ci-pipeline-scheduler/             #   CI scheduler with resource pools (hard)
  cicd-secrets-leak-scanner/         #   secrets detection across CI configs (hard)
  compose-guard/                     #   Docker Compose linter + extends (hard)
  container-image-security-audit/    #   container security auditor (hard)
  cron-guard/                        #   cron config static analyzer (hard)
  git-hook-generator/                #   git hook generator from config (medium)

runner/
  coding-task-runner.ts              # CodingTaskRunner (clone, run, verify, metrics)
  api-eval.ts                        # Gemini REST API evaluator (Tier 1)
  challenge-eval.ts                  # Docker-based evaluator (Tier 2)
  modal_challenge_eval.py            # Modal cloud evaluator (Tier 2)
  metrics.ts                         # RFS, PES, CCS, TER implementations
  failure-taxonomy.ts                # 7-mode failure classification
  run-eval.ts                        # CLI entry point (dry-run + live)
  stats.ts                           # dataset summary stats

pipeline/
  mine_tasks.py                      # PR mining (GitHub API)
  validate_task.py                   # schema + semantic validation
  analyze_activity_log.ts            # activity log analysis

results/                             # evaluation results (JSON)
docs/                                # design docs (taxonomy, architecture, criteria)
examples/                            # demo eval using TestRig pattern
```

## Metrics

| Metric | What it measures |
|--------|-----------------|
| **RFS** (Reasoning Forcing Score) | How much cross-component reasoning a task demands |
| **PES** (Path Efficiency Score) | How efficiently the agent navigated to the solution |
| **CCS** (Context Coverage Score) | What fraction of required context the agent consumed |
| **TER** (Tool Efficiency Ratio) | Ratio of productive tool calls to total |

## Failure taxonomy

| Mode | Description |
|------|-------------|
| `context_insufficient` | Agent didn't read enough context files |
| `wrong_files_targeted` | Agent edited files outside expected change set |
| `shallow_fix` | Minimal change that doesn't address root cause |
| `cross_component_miss` | Fixed one file, missed related changes |
| `test_regression` | Fix introduced new failures |
| `timeout` | Exceeded time limit |
| `complete_hallucination` | Changes unrelated to the task |

## Integration with Gemini CLI

Designed to work with the existing eval infrastructure:

- `CodingTaskManifest` extends the [`EvalCase`](https://github.com/google-gemini/gemini-cli/blob/main/evals/test-helper.ts#L199-L207) pattern
- `CodingTaskRunner` wraps [`TestRig`](https://github.com/google-gemini/gemini-cli/blob/main/packages/test-utils/src/test-rig.ts)
- Results feed into [`aggregate_evals.js`](https://github.com/google-gemini/gemini-cli/blob/main/scripts/aggregate_evals.js)
- Eval policies (`ALWAYS_PASSES` / `USUALLY_PASSES`) map to difficulty levels

See [docs/architecture.md](docs/architecture.md) for the full design.

## License

Apache-2.0

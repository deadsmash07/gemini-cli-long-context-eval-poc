# Challenge Tasks (Tier 2)

7 expert-designed, Docker-containerized coding challenges that test complex reasoning, multi-module debugging, and system design. These are harder than the PR-mined tasks and are verified to challenge SOTA models in RL evaluation environments.

## Why these exist

The PR-mined tasks (Tier 1) are ecologically valid but mostly L2-L3 difficulty. Real-world agent failures often happen on harder problems: tasks where bugs are spread across multiple modules, where the instruction is deliberately minimal, and where naive pattern-matching produces code that passes some tests but fails edge cases. These challenge tasks fill the L3-L4 gap.

Zero contamination risk - these are original tasks, not derived from public repositories.

## Evaluation Results (Modal Cloud, March 2026)

Ran all 7 tasks on Modal cloud VMs across 3 Gemini models:

| Task | Difficulty | 2.5-flash | 3-pro | 3.1-pro |
|------|-----------|-----------|-------|---------|
| build-queue-coordinator | Medium | 0/1 (err) | timeout | timeout |
| ci-pipeline-scheduler | Hard | 0/1 (err) | timeout | timeout |
| cicd-secrets-leak-scanner | Hard | 1/30 (3%) | timeout | timeout |
| compose-guard | Hard | 0/6 (0%) | timeout | timeout |
| container-image-security-audit | Hard | 0/26 (0%) | timeout | timeout |
| cron-guard | Hard | 1/10 (10%) | timeout | timeout |
| git-hook-generator | Medium | 0/31 (0%) | 1/31 (3%) | 1/31 (3%) |

**0 out of 7 tasks fully solved by any model.** Flash completed all 7 tasks (best: cron-guard at 10%). Pro models timed out on 6/7 tasks due to slower generation. On the one task Pro finished (git-hook-generator), both 3-pro and 3.1-pro passed 1 test vs Flash's 0 - suggesting Pro may reason better given enough time but at much higher latency.

These tasks require multi-step reasoning, careful specification reading, and coordinated implementation across modules that single-turn LLM generation cannot handle.

## Tasks

| Task | Difficulty | Category | Tests | Description |
|------|-----------|----------|-------|-------------|
| build-queue-coordinator | Medium | Software Engineering | 40+ | Fix a broken CI/CD build queue with priority aging, preemption, retries, dependency tracking, and resource pools across 5 Python modules |
| ci-pipeline-scheduler | Hard | Software Engineering | 30+ | Fix a CI pipeline scheduler with resource constraints, priority queuing, and concurrent execution |
| cicd-secrets-leak-scanner | Hard | DevOps Security | 20+ | Build a secrets detection tool that scans YAML/JSON CI configs for credentials, JWTs, and API keys with severity scoring |
| compose-guard | Hard | Software Engineering | 15+ | Build a CLI that parses Docker Compose files, resolves extends/inheritance across files, and enforces security policies |
| container-image-security-audit | Hard | Security | 20+ | Build a container image security auditor that analyzes Dockerfiles and running containers |
| cron-guard | Hard | Security | 15+ | Build a cron configuration static analyzer and security linter |
| git-hook-generator | Medium | DevOps | 20+ | Build a git hook generator that creates pre-commit, pre-push, and other hooks from config |

## Structure

Each task follows a consistent format:

```
task-name/
  task.toml          # Metadata: difficulty, category, tags, timeouts, resource limits
  instruction.md     # Task prompt (what the agent sees)
  environment/       # Docker setup + buggy/skeleton code
    Dockerfile       # Container definition
    *.py             # Source files with bugs or skeleton implementations
  solution/
    solve.sh         # Reference solution (ground truth)
  tests/
    test_*.py        # Comprehensive test suite for verification
```

## Running a task

Each task runs inside a Docker container:

```bash
# Build the environment
cd challenge-tasks/build-queue-coordinator
docker build -t bqc-eval environment/

# Run tests (should fail on the buggy code)
docker run bqc-eval pytest tests/ -v

# Apply solution and verify
docker run bqc-eval bash -c "bash solution/solve.sh && pytest tests/ -v"
```

## Design properties

- **Self-contained**: each task includes everything needed to run, verify, and grade
- **Deterministic verification**: pytest test suites with specific assertions, not fuzzy matching
- **Multi-module**: bugs are deliberately spread across files to require cross-module reasoning
- **Minimal instructions**: prompts describe what the code should do, not where the bugs are
- **Resource-constrained**: Docker containers have CPU, memory, and storage limits defined in task.toml

## Connection to the evaluation dataset

These tasks complement the PR-mined tasks (Tier 1) in the same way that Colab-Bench combines automated task extraction with expert-designed challenges. Automated mining gives ecological validity and scale; hand-crafted tasks give difficulty control and contamination resistance. The full dataset benefits from both.

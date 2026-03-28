# Repository Selection Criteria

## Overview

This document defines the criteria for selecting open-source repositories from
which coding evaluation tasks are mined. Repository selection directly affects
dataset quality: poorly chosen repos produce tasks that are either trivially
solvable, impossible to verify, or contaminated by training data.

The criteria are designed to maximize three properties:

1. **Ecological validity** -- tasks come from real codebases with real
   development practices, not synthetic benchmarks.
2. **Verifiability** -- every mined task can be verified by running an
   existing test suite or checking a deterministic output.
3. **Contamination resistance** -- tasks are unlikely to appear verbatim in
   model training data.

---

## Selection Criteria Matrix

| Criterion | Requirement | Rationale |
|---|---|---|
| Language | Must be in {Python, TypeScript/JavaScript, Go, Rust, Java, C++} | Covers the top 6 languages in open-source contribution volume and LLM benchmark coverage |
| Size | 5,000 - 500,000 LOC | Large enough for meaningful cross-file and architectural tasks; small enough to clone and index within eval infrastructure limits |
| Stars | > 1,000 | Indicates real-world adoption; repos with fewer stars often have idiosyncratic practices that reduce generalizability |
| Activity | At least one commit in the last 6 months | Ensures active maintenance; stale repos have unresolved issues that complicate task verification |
| License | OSI-approved permissive license (MIT, Apache-2.0, BSD-2-Clause, BSD-3-Clause) | Legal clarity for inclusion in a publicly distributed benchmark |
| Test suite | CI pipeline passes on pinned commit; > 50% line coverage | Enables functional verification of agent-produced patches |
| PR hygiene | Descriptive commit messages; issues linked to PRs | Enables automated task mining from PR metadata and commit history |
| Documentation | README with build instructions; contribution guidelines | Ensures the repo can be set up programmatically for eval runs |
| Build reproducibility | Deterministic build from pinned dependencies (lockfile present) | Prevents flaky eval failures from dependency drift |

---

## Contamination Resistance

Training data contamination is the primary threat to benchmark validity. If a
model has seen the exact PR, issue, or code change during training, it can
produce the correct patch from memorization rather than reasoning. The
following measures mitigate this:

### Pin to Specific Commit SHAs

Every task manifest references a specific commit SHA as the starting state. The
agent receives a clone at that exact commit. This prevents the task from
drifting as the upstream repo evolves and provides a stable baseline for
reproduction.

### Prefer Recent PRs

Prefer PRs merged after known model training data cutoffs. For current frontier
models (training data through mid-2025), prioritize PRs merged in late 2025 and
2026. This is the single most effective contamination mitigation: if the data
did not exist when the model was trained, it cannot be memorized.

### Contamination Verification Protocol

For each candidate task, run the following check before inclusion:

1. Present the task prompt to the target model **without tool access** (no
   file reads, no grep, no repository context).
2. If the model produces a correct or near-correct patch from the prompt
   alone, the task is contaminated. Discard it.
3. If the model produces a plausible but incorrect patch, the task is
   borderline. Flag it for manual review.
4. If the model cannot produce a meaningful patch without tool access, the
   task passes the contamination check.

This protocol should be run against the primary evaluation targets (Gemini
models) and at least one other frontier model (e.g., Claude, GPT) to catch
broad contamination.

### Structural Diversification

- Use non-default branches when the relevant work happened on a feature branch.
- Prefer less-popular repositories (1,000-10,000 stars) over hyper-popular ones
  (100k+ stars) when task quality is comparable. Hyper-popular repos are
  over-represented in training corpora.
- Avoid repos that are themselves benchmarks or evaluation tools, as these are
  disproportionately likely to appear in training data.

---

## Domain Diversity Target

Tasks should span multiple software domains to avoid over-fitting the
benchmark to a narrow problem type. The target distribution:

| Domain | Target % | Example Repositories |
|---|---|---|
| Web frameworks | 25% | FastAPI, Express, Flask, Django, Actix-web |
| CLI / Developer tools | 20% | Ruff, ESLint, Deno, Cargo plugins, Biome |
| Data processing | 15% | Pandas, Polars, Arrow, DuckDB bindings |
| ML/AI libraries | 15% | PyTorch extensions, Transformers, ONNX Runtime |
| Systems / Infrastructure | 15% | Docker tooling, Kubernetes operators, Terraform providers |
| Other | 10% | General-purpose libraries, compression, serialization, protocol implementations |

**Rationale:** This distribution reflects the domains where AI coding agents
are most likely to be deployed. Web and CLI tools dominate developer workflows,
so they receive the largest share. Systems and ML libraries test the agent's
ability to handle performance-sensitive and mathematically grounded code.

---

## Language Distribution Target

| Language | Target % | Rationale |
|---|---|---|
| Python | 30% | Largest OSS ecosystem; most common in AI/ML and web backend |
| TypeScript / JavaScript | 25% | Dominant in web frontend and tooling; tests type system reasoning |
| Rust | 15% | Tests reasoning about ownership, lifetimes, and borrow checker constraints |
| Go | 15% | Common in infrastructure tooling; tests reasoning about concurrency and interfaces |
| Java | 10% | Enterprise patterns; tests reasoning about class hierarchies and dependency injection |
| C++ | 5% | Systems programming; tests reasoning about memory management and build systems |

**Note on TypeScript vs. JavaScript:** These are grouped because most modern
repositories use TypeScript, and tasks that involve JavaScript files typically
exist in a TypeScript-configured project. The eval infrastructure treats them
as a single language category.

**Note on C++:** The 5% allocation reflects practical constraints -- C++
repositories have significantly higher build complexity, longer compilation
times, and more fragile CI setups, all of which increase eval infrastructure
costs. The small allocation still provides coverage for this important language
without disproportionate infrastructure burden.

---

## Candidate Repository List

The following repositories are initial candidates, subject to validation against
the full criteria matrix. This list is not exhaustive and will be expanded
during the mining phase.

### Python
- **FastAPI** (tiangolo/fastapi) -- Web framework, ~30k LOC, MIT
- **Ruff** (astral-sh/ruff) -- Linter/formatter, Python + Rust, MIT
- **Polars** (pola-rs/polars) -- DataFrame library, Rust + Python bindings, MIT
- **httpx** (encode/httpx) -- HTTP client, ~15k LOC, BSD-3

### TypeScript / JavaScript
- **Biome** (biomejs/biome) -- Toolchain, Rust + TS, MIT
- **tRPC** (trpc/trpc) -- TypeScript RPC framework, ~20k LOC, MIT
- **Turborepo** (vercel/turborepo) -- Build system, Go + TS, MIT

### Rust
- **Axum** (tokio-rs/axum) -- Web framework, ~20k LOC, MIT
- **Nushell** (nushell/nushell) -- Shell, ~200k LOC, MIT

### Go
- **k9s** (derailed/k9s) -- Kubernetes TUI, ~80k LOC, Apache-2.0
- **Cobra** (spf13/cobra) -- CLI framework, ~10k LOC, Apache-2.0

### Java
- **Quarkus** (quarkusio/quarkus) -- Cloud-native framework, Apache-2.0

### C++
- **DuckDB** (duckdb/duckdb) -- Analytical database, MIT

---

## Validation Process

For each candidate repository:

1. **Clone and build.** Verify the build succeeds from a clean checkout at
   the pinned commit on a standard CI environment (Ubuntu 22.04+, standard
   toolchains).

2. **Run test suite.** Verify tests pass. Record coverage if available.
   Repos where the test suite requires external services (databases, cloud
   APIs) that cannot be mocked are deprioritized.

3. **Mine candidate PRs.** Run the PR mining script against the last 12
   months of merged PRs. Verify that at least 5 candidate tasks pass
   schema validation.

4. **Check contamination.** Run the contamination verification protocol on
   2-3 candidate tasks per repository.

5. **Record metadata.** Store the repository's validated properties
   (commit SHA, LOC, coverage, number of candidate tasks) in the
   repository registry.

Repositories that fail any of steps 1-3 are excluded. Repositories that
fail step 4 on all candidate tasks are excluded. Partial contamination
(some tasks contaminated, others not) is acceptable -- contaminated tasks
are simply discarded.

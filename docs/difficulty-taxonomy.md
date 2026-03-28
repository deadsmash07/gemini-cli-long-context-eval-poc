# Difficulty Taxonomy for Long-Context Coding Tasks

## Overview

This document defines a 4-level difficulty taxonomy for coding evaluation tasks.
The taxonomy is designed to systematically probe an AI agent's ability to reason
over increasing spans of code context, from single-file fixes to multi-subsystem
investigations requiring hypothesis-driven debugging.

Each level corresponds to a qualitatively different mode of reasoning. This is
not an arbitrary binning by line count -- the levels reflect distinct cognitive
demands that map to observable differences in agent behavior, tool-use patterns,
and failure modes.

---

## Level 1 -- Localized (Single-file)

| Property | Value |
|---|---|
| Context window | < 500 lines, 1 file |
| Reasoning type | Direct pattern match, localized fix |
| Agent behavior | Read file -> identify issue -> edit |
| Expected tool calls | 2-5 (read + edit) |
| Eval policy | `ALWAYS_PASSES` (deterministic) |

**Characteristics:**

- The bug or task is fully contained within a single file.
- The fix requires no understanding of external interfaces, imports, or
  module-level architecture.
- A correct solution can be produced by reading the relevant file and applying
  a local transformation.

**Examples:**

- Fix a typo in an error message string.
- Correct an off-by-one error in a loop bound.
- Add a missing `return` statement in a function with an obvious control flow gap.
- Update a hardcoded constant to match a documented specification.

**Failure modes at this level indicate:** The agent cannot perform basic code
comprehension or has fundamental tool-use failures. Any model that fails
consistently at L1 is not viable for agentic coding.

---

## Level 2 -- Cross-file (Multi-file Dependency)

| Property | Value |
|---|---|
| Context window | 500-3000 lines, 2-5 files |
| Reasoning type | Trace imports, understand interface contracts |
| Agent behavior | Search -> read multiple files -> understand dependency -> edit |
| Expected tool calls | 5-15 (grep + multiple reads + edits) |
| Eval policy | `ALWAYS_PASSES` or `USUALLY_PASSES` |

**Characteristics:**

- The task requires understanding how two or more files interact.
- The agent must trace import chains, function call sites, or shared type
  definitions to identify the root cause or implement the change correctly.
- Edits in one file must be consistent with contracts defined in another.

**Examples:**

- Fix a regression where a change to a utility function's return type breaks
  two downstream callers in different modules.
- Implement a new configuration option that requires changes to both the config
  parser and the module that consumes the parsed value.
- Resolve a type mismatch between a function signature and its call site
  across module boundaries.

**Failure modes at this level indicate:** The agent cannot maintain coherent
state across multiple files, or its search strategy is too narrow to discover
relevant dependencies.

---

## Level 3 -- Architectural (Module-graph Comprehension)

| Property | Value |
|---|---|
| Context window | 3000-15000 lines, 5-15 files |
| Reasoning type | Understand module dependency graph, build system, test structure |
| Agent behavior | Investigate structure -> map dependencies -> plan -> implement across files |
| Expected tool calls | 15-40 (extensive search + investigation + multi-file edits) |
| Eval policy | `USUALLY_PASSES` |

**Characteristics:**

- The task requires understanding the project's architectural structure:
  module boundaries, dependency graph, build configuration, and test
  organization.
- The agent must form a mental model of how subsystems relate before it can
  plan a correct implementation.
- Changes typically span 5+ files and must maintain architectural invariants
  (e.g., layering constraints, error handling conventions, test coverage
  expectations).

**Examples:**

- Refactor error handling across a subsystem to use a new error type, updating
  all producers and consumers of errors within that subsystem.
- Add a new middleware layer that integrates with existing request processing
  pipeline, authentication, and logging infrastructure.
- Migrate a module from synchronous to asynchronous I/O, updating all
  call sites, tests, and integration points.

**Failure modes at this level indicate:** The agent lacks the ability to build
and maintain a sufficiently rich model of project structure, or its planning
capacity breaks down when changes must be coordinated across many files.

---

## Level 4 -- Multi-step Reasoning (Investigation Chain)

| Property | Value |
|---|---|
| Context window | 15000+ lines, 10+ files |
| Reasoning type | Hypothesis formation, debugging chain, architectural decision-making |
| Agent behavior | Investigate -> form hypothesis -> test -> refine -> implement solution |
| Expected tool calls | 40+ (deep investigation + trial/error + implementation) |
| Eval policy | `USUALLY_PASSES` |

**Characteristics:**

- The task requires an extended chain of reasoning with intermediate
  hypotheses that may be revised as new evidence is gathered.
- The root cause is not obvious from any single file or even any small set
  of files -- it emerges from the interaction of multiple subsystems.
- The agent must engage in genuine debugging: forming hypotheses, gathering
  evidence, ruling out alternatives, and iterating toward a solution.

**Examples:**

- Debug a panic that only occurs with specific input combinations and
  involves race conditions across three subsystems.
- Diagnose and fix a performance regression caused by an unintended
  interaction between caching logic and a recent schema migration.
- Resolve a CI failure that reproduces only in the nightly build due to
  environment-dependent initialization ordering.

**Failure modes at this level indicate:** The agent cannot sustain coherent
multi-step reasoning, loses track of its investigation state, or lacks the
ability to revise hypotheses in light of contradicting evidence.

---

## Distribution Target

The dataset targets the following distribution across difficulty levels:

| Level | Name | Target % | Count (n=50) | Rationale |
|---|---|---|---|---|
| L1 | Localized | 20% | 10 | Baseline competence; quick signal |
| L2 | Cross-file | 40% | 20 | Core agentic capability; highest discriminative value |
| L3 | Architectural | 25% | 12-13 | Tests planning and structural reasoning |
| L4 | Multi-step | 15% | 7-8 | Ceiling tasks; separates frontier models |

**Why this distribution:**

- L2 gets the largest share because cross-file reasoning is the primary
  capability gap between tool-augmented LLMs and human developers. Most
  real-world coding tasks fall in this range, and it is where model
  improvements yield the most practical value.
- L1 is kept small because it provides limited signal -- most capable models
  pass L1 tasks consistently, so over-representing them wastes evaluation
  budget.
- L4 is kept small because these tasks are expensive to mine, validate, and
  run, and they exhibit high variance even for strong models.

---

## Connection to Hierarchical Reasoning Research

This taxonomy is informed by research on how LLMs encode hierarchical
structure during reasoning. Work on mechanistic interpretability of reasoning
models (Rastogi, ICLR 2026) demonstrates that transformer layers encode
progressively more abstract representations:

- **Shallow layers** process surface-level patterns: token co-occurrence,
  syntactic structure, local variable scope. This corresponds to L1 tasks,
  where the solution is identifiable from local syntactic and semantic cues
  within a single file.

- **Middle layers** build relational representations: function call graphs,
  type relationships, import chains. This corresponds to L2 tasks, where the
  agent must trace dependencies across file boundaries and maintain coherent
  understanding of interface contracts.

- **Deep layers** encode abstract structural properties: module roles,
  architectural invariants, system-level interaction patterns. This
  corresponds to L3 tasks, where the agent must understand how subsystems
  compose and maintain architectural consistency across coordinated changes.

- **The full-depth reasoning chain** -- where all layers must coordinate to
  sustain a multi-step inference process -- corresponds to L4 tasks. These
  tasks require the model to maintain and revise an evolving hypothesis over
  many reasoning steps, integrating evidence gathered across the full
  codebase.

This mapping is not merely analogical. If hierarchical encoding is a real
property of how these models process code (as the mechanistic evidence
suggests), then a difficulty taxonomy that tracks the depth of abstraction
required should produce cleaner separability between model capability tiers
than taxonomies based on surface metrics like line count or file count alone.

The practical implication: when a model fails at L3 but passes L2, this
points to a specific deficit in architectural-level representation, not a
generic "the task was harder" explanation. This makes the taxonomy
diagnostically useful for model development, not just for ranking.

---

## Assigning Difficulty Levels

When mining tasks from real repositories, assign levels using these criteria
in order of priority:

1. **Number of files the ground-truth patch touches.** This is the strongest
   single signal. 1 file = likely L1. 2-5 files = likely L2. 5+ files = L3
   or L4.

2. **Whether the fix requires understanding code not in the patch.** If the
   patch touches 2 files but the developer needed to read 8 files to
   understand the problem, that is L3 or L4, not L2.

3. **Whether the PR discussion mentions investigation or debugging.** PRs
   where the author describes ruling out hypotheses or iterating on a fix
   are strong L4 candidates.

4. **The semantic distance between symptom and root cause.** If the bug
   manifests in module A but the fix is in module C (reachable only through
   B), the task is at least L3.

When in doubt, assign the higher level. It is better to overestimate
difficulty (and have the task be easier than expected) than to underestimate
it (and have a task that trivially passes provide no signal).

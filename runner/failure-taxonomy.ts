/**
 * @license
 * Copyright 2026 Google LLC
 * SPDX-License-Identifier: Apache-2.0
 */

/**
 * Failure classification for coding task evaluations.
 *
 * Seven failure modes are defined, covering the spectrum from insufficient
 * context gathering to complete hallucination. The classifyFailure function
 * examines the manifest, activity log, and verification results to determine
 * the most likely failure mode.
 */

import type {
  CodingTaskManifest,
  ToolCallRecord,
  VerificationResult,
} from './coding-task-runner.js';
import { READ_TOOLS, EDIT_TOOLS } from './coding-task-runner.js';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type FailureMode =
  | 'context_insufficient'
  | 'wrong_files_targeted'
  | 'shallow_fix'
  | 'cross_component_miss'
  | 'test_regression'
  | 'timeout'
  | 'complete_hallucination';

export interface FailureClassification {
  mode: FailureMode;
  confidence: number;      // 0.0 - 1.0
  evidence: string;        // human-readable explanation
  secondaryMode?: FailureMode;
  secondaryConfidence?: number;
}

export const FAILURE_DESCRIPTIONS: Record<FailureMode, string> = {
  context_insufficient:   'Agent did not read enough context files to understand the task',
  wrong_files_targeted:   'Agent edited files not in the expected change set',
  shallow_fix:            'Agent made a minimal change that does not address the root cause',
  cross_component_miss:   'Agent fixed one component but missed related changes in others',
  test_regression:        'Agent\'s fix introduced new test failures',
  timeout:                'Agent exceeded the time limit without completing',
  complete_hallucination: 'Agent\'s changes are unrelated to the task',
};

// ---------------------------------------------------------------------------
// Classification logic
// ---------------------------------------------------------------------------

export function classifyFailure(
  manifest: CodingTaskManifest,
  toolCalls: ToolCallRecord[],
  verification: VerificationResult,
  timedOut = false,
): FailureClassification {

  // ---- Timeout is unambiguous ----
  if (timedOut) {
    return {
      mode: 'timeout',
      confidence: 1.0,
      evidence: 'Agent exceeded the configured time limit',
    };
  }

  // Compute derived signals
  const contextFiles = new Set(manifest.context_files);
  const filesRead = new Set<string>();
  const filesEdited = new Set<string>();

  for (const call of toolCalls) {
    if (READ_TOOLS.has(call.type) && call.file) filesRead.add(call.file);
    if (EDIT_TOOLS.has(call.type) && call.file) filesEdited.add(call.file);
  }

  const contextReadCount = [...contextFiles].filter(f => filesRead.has(f)).length;
  const contextCoverage = contextFiles.size > 0
    ? contextReadCount / contextFiles.size
    : 0;

  const expectedHit = verification.expectedFilesHit.length;
  const expectedTotal = manifest.verification.expected_files_changed.length;
  const unexpectedCount = verification.unexpectedFilesChanged.length;
  const missingCount = verification.missingExpectedFiles.length;
  const editCount = toolCalls.filter(c => EDIT_TOOLS.has(c.type)).length;

  // ---- Complete hallucination: edited files are entirely unrelated ----
  if (expectedHit === 0 && unexpectedCount > 0) {
    return {
      mode: 'complete_hallucination',
      confidence: 0.9,
      evidence:
        `Edited ${unexpectedCount} file(s) outside expected set, ` +
        `none of the ${expectedTotal} expected files were touched`,
      secondaryMode: contextCoverage < 0.3 ? 'context_insufficient' : undefined,
      secondaryConfidence: contextCoverage < 0.3 ? 0.6 : undefined,
    };
  }

  // ---- Context insufficient: agent barely explored the codebase ----
  if (contextCoverage < 0.3) {
    return {
      mode: 'context_insufficient',
      confidence: 0.85,
      evidence:
        `Read ${contextReadCount}/${contextFiles.size} context files ` +
        `(${(contextCoverage * 100).toFixed(0)}% coverage)`,
      secondaryMode: missingCount > 0 ? 'cross_component_miss' : undefined,
      secondaryConfidence: missingCount > 0 ? 0.5 : undefined,
    };
  }

  // ---- Wrong files targeted: more unexpected edits than expected ones ----
  if (unexpectedCount > expectedHit) {
    return {
      mode: 'wrong_files_targeted',
      confidence: 0.8,
      evidence:
        `${unexpectedCount} unexpected file(s) changed vs ` +
        `${expectedHit}/${expectedTotal} expected file(s) hit`,
    };
  }

  // ---- Cross-component miss: some expected files fixed, others not ----
  if (missingCount > 0 && expectedHit > 0) {
    return {
      mode: 'cross_component_miss',
      confidence: 0.75,
      evidence:
        `Fixed ${expectedHit}/${expectedTotal} components; ` +
        `missed: ${verification.missingExpectedFiles.join(', ')}`,
    };
  }

  // ---- Test regression vs shallow fix (agent hit the right files) ----
  if (!verification.testsPassed && missingCount === 0) {
    // Agent edited all expected files but tests still fail
    if (editCount <= 2) {
      return {
        mode: 'shallow_fix',
        confidence: 0.7,
        evidence:
          `Only ${editCount} edit operation(s); ` +
          `correct files targeted but tests still fail`,
        secondaryMode: 'test_regression',
        secondaryConfidence: 0.4,
      };
    }
    return {
      mode: 'test_regression',
      confidence: 0.7,
      evidence:
        `${editCount} edits across correct files but tests fail; ` +
        `changes may have introduced regressions`,
      secondaryMode: 'shallow_fix',
      secondaryConfidence: 0.3,
    };
  }

  // ---- Fallback: shallow fix ----
  return {
    mode: 'shallow_fix',
    confidence: 0.5,
    evidence: 'Task failed without matching a specific high-confidence failure pattern',
  };
}

/**
 * @license
 * Copyright 2026 Google LLC
 * SPDX-License-Identifier: Apache-2.0
 */

/**
 * Novel evaluation metrics for long-context coding tasks.
 *
 * Four metrics are implemented:
 *   1. RFS  -- Reasoning Forcing Score (task difficulty signal)
 *   2. PES  -- Path Efficiency Score (navigation efficiency)
 *   3. CCS  -- Context Coverage Score (context consumption)
 *   4. TER  -- Tool Efficiency Ratio (productive vs total tool calls)
 *
 * Each function returns a MetricResult with the numeric value,
 * a human-readable interpretation, and threshold-based rating.
 */

import type { CodingTaskManifest, ToolCallRecord } from './coding-task-runner.js';
import { READ_TOOLS, EDIT_TOOLS } from './coding-task-runner.js';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type Rating = 'good' | 'warning' | 'poor';

export interface MetricResult {
  name: string;
  value: number;
  rating: Rating;
  interpretation: string;
}

// ---------------------------------------------------------------------------
// RFS -- Reasoning Forcing Score
// ---------------------------------------------------------------------------

/**
 * Measures how much cross-component reasoning a task demands.
 *
 *   RFS = (files_must_read - files_in_diff) * cross_reference_weight + dependency_depth
 *
 * - files_must_read:         context_files.length from the manifest
 * - files_in_diff:           expected_files_changed.length from verification
 * - cross_reference_weight:  estimated cross-file dependency edges (capped at
 *                            files_must_read to stay proportional)
 * - dependency_depth:        approximated from difficulty level (1-4)
 *
 * Higher RFS means the task requires more reasoning across components.
 *
 * Thresholds:
 *   good    (>= 6): significant cross-component reasoning required
 *   warning (>= 3): moderate reasoning across a few files
 *   poor    (< 3):  minimal cross-file reasoning needed
 */
export function computeRFS(manifest: CodingTaskManifest): MetricResult {
  const filesMustRead = manifest.context_files.length;
  const filesInDiff = manifest.verification.expected_files_changed.length;

  // Approximate cross-reference weight: the more context files beyond the diff,
  // the more cross-referencing is implied. Cap at number of context files.
  const crossReferenceWeight = Math.min(filesMustRead, 3);

  // Dependency depth approximation from difficulty tier
  const dependencyDepth = manifest.difficulty;

  const rfs = (filesMustRead - filesInDiff) * crossReferenceWeight + dependencyDepth;

  let rating: Rating;
  let interpretation: string;

  if (rfs >= 6) {
    rating = 'good';
    interpretation = `RFS ${rfs.toFixed(1)}: task requires significant cross-component reasoning`;
  } else if (rfs >= 3) {
    rating = 'warning';
    interpretation = `RFS ${rfs.toFixed(1)}: moderate cross-file reasoning needed`;
  } else {
    rating = 'poor';
    interpretation = `RFS ${rfs.toFixed(1)}: minimal reasoning demand; consider a harder task`;
  }

  return { name: 'RFS', value: rfs, rating, interpretation };
}

// ---------------------------------------------------------------------------
// PES -- Path Efficiency Score
// ---------------------------------------------------------------------------

/**
 * How efficiently the agent navigated to the solution.
 *
 *   PES = relevant_files_read / total_files_read
 *
 * Where relevant_files_read = files in context_files that were actually read.
 * A score of 1.0 means the agent only read files that were relevant.
 *
 * Thresholds:
 *   good    (>= 0.6): agent focused on relevant files
 *   warning (>= 0.3): some exploration, but mostly on target
 *   poor    (< 0.3):  agent spent most effort on irrelevant files
 */
export function computePES(
  manifest: CodingTaskManifest,
  toolCalls: ToolCallRecord[],
): MetricResult {
  const contextFiles = new Set(manifest.context_files);
  const allFilesRead = new Set<string>();
  const relevantFilesRead = new Set<string>();

  for (const call of toolCalls) {
    if (READ_TOOLS.has(call.type) && call.file) {
      allFilesRead.add(call.file);
      if (contextFiles.has(call.file)) {
        relevantFilesRead.add(call.file);
      }
    }
  }

  const totalReads = allFilesRead.size;
  const pes = totalReads > 0 ? relevantFilesRead.size / totalReads : 0;

  let rating: Rating;
  let interpretation: string;

  if (pes >= 0.6) {
    rating = 'good';
    interpretation = `PES ${pes.toFixed(2)}: agent navigated efficiently (${relevantFilesRead.size}/${totalReads} files relevant)`;
  } else if (pes >= 0.3) {
    rating = 'warning';
    interpretation = `PES ${pes.toFixed(2)}: moderate exploration (${relevantFilesRead.size}/${totalReads} relevant)`;
  } else {
    rating = 'poor';
    interpretation = `PES ${pes.toFixed(2)}: excessive wandering (${relevantFilesRead.size}/${totalReads} relevant)`;
  }

  return { name: 'PES', value: pes, rating, interpretation };
}

// ---------------------------------------------------------------------------
// CCS -- Context Coverage Score
// ---------------------------------------------------------------------------

/**
 * What fraction of required context the agent consumed.
 *
 *   CCS = files_from_context_read / total_context_files
 *
 * A score of 1.0 means the agent read all required context files.
 *
 * Thresholds:
 *   good    (>= 0.7): agent consumed most of the required context
 *   warning (>= 0.4): partial context consumption
 *   poor    (< 0.4):  agent missed most required context
 */
export function computeCCS(
  manifest: CodingTaskManifest,
  toolCalls: ToolCallRecord[],
): MetricResult {
  const contextFiles = new Set(manifest.context_files);
  const filesRead = new Set<string>();

  for (const call of toolCalls) {
    if (READ_TOOLS.has(call.type) && call.file) {
      filesRead.add(call.file);
    }
  }

  const contextRead = [...contextFiles].filter(f => filesRead.has(f));
  const ccs = contextFiles.size > 0 ? contextRead.length / contextFiles.size : 0;

  let rating: Rating;
  let interpretation: string;

  if (ccs >= 0.7) {
    rating = 'good';
    interpretation = `CCS ${ccs.toFixed(2)}: read ${contextRead.length}/${contextFiles.size} context files`;
  } else if (ccs >= 0.4) {
    rating = 'warning';
    interpretation = `CCS ${ccs.toFixed(2)}: partial coverage (${contextRead.length}/${contextFiles.size} context files)`;
  } else {
    rating = 'poor';
    interpretation = `CCS ${ccs.toFixed(2)}: missed most context (${contextRead.length}/${contextFiles.size})`;
  }

  return { name: 'CCS', value: ccs, rating, interpretation };
}

// ---------------------------------------------------------------------------
// TER -- Tool Efficiency Ratio
// ---------------------------------------------------------------------------

/**
 * Ratio of productive tool calls to total tool calls.
 *
 *   TER = (edit_calls + targeted_read_calls) / total_tool_calls
 *
 * Where targeted_read_calls = read calls on files within the context set.
 * Higher TER means the agent wasted fewer calls on non-productive actions.
 *
 * Thresholds:
 *   good    (>= 0.5): majority of tool calls were productive
 *   warning (>= 0.25): noticeable overhead from non-productive calls
 *   poor    (< 0.25): mostly non-productive tool usage
 */
export function computeTER(
  manifest: CodingTaskManifest,
  toolCalls: ToolCallRecord[],
): MetricResult {
  const contextFiles = new Set(manifest.context_files);
  const total = toolCalls.length;

  if (total === 0) {
    return {
      name: 'TER',
      value: 0,
      rating: 'poor',
      interpretation: 'TER 0.00: no tool calls recorded',
    };
  }

  const editCalls = toolCalls.filter(c => EDIT_TOOLS.has(c.type)).length;
  const targetedReads = toolCalls.filter(
    c => READ_TOOLS.has(c.type) && c.file && contextFiles.has(c.file),
  ).length;

  const ter = (editCalls + targetedReads) / total;

  let rating: Rating;
  let interpretation: string;

  if (ter >= 0.5) {
    rating = 'good';
    interpretation = `TER ${ter.toFixed(2)}: ${editCalls} edits + ${targetedReads} targeted reads / ${total} total calls`;
  } else if (ter >= 0.25) {
    rating = 'warning';
    interpretation = `TER ${ter.toFixed(2)}: some overhead (${editCalls} edits + ${targetedReads} targeted reads / ${total})`;
  } else {
    rating = 'poor';
    interpretation = `TER ${ter.toFixed(2)}: high overhead (${editCalls} edits + ${targetedReads} targeted reads / ${total})`;
  }

  return { name: 'TER', value: ter, rating, interpretation };
}

// ---------------------------------------------------------------------------
// Convenience: compute all metrics at once
// ---------------------------------------------------------------------------

export interface AllMetrics {
  rfs: MetricResult;
  pes: MetricResult;
  ccs: MetricResult;
  ter: MetricResult;
}

export function computeAllMetrics(
  manifest: CodingTaskManifest,
  toolCalls: ToolCallRecord[],
): AllMetrics {
  return {
    rfs: computeRFS(manifest),
    pes: computePES(manifest, toolCalls),
    ccs: computeCCS(manifest, toolCalls),
    ter: computeTER(manifest, toolCalls),
  };
}

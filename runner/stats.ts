/**
 * @license
 * Copyright 2026 Google LLC
 * SPDX-License-Identifier: Apache-2.0
 */

/**
 * Quick stats script: reads all task manifests and prints a summary table.
 *
 * Usage:
 *   npx tsx runner/stats.ts [--dir schema/sample-tasks/]
 */

import * as fs from 'fs';
import * as path from 'path';
import { loadAllManifests, type CodingTaskManifest } from './coding-task-runner.js';
import { computeRFS } from './metrics.js';

// ---------------------------------------------------------------------------
// CLI arg parsing
// ---------------------------------------------------------------------------

function getTasksDir(): string {
  const idx = process.argv.indexOf('--dir');
  if (idx !== -1 && process.argv[idx + 1]) {
    return process.argv[idx + 1];
  }
  // Default: schema/sample-tasks/ relative to project root
  return path.resolve(path.dirname(new URL(import.meta.url).pathname), '..', 'schema', 'sample-tasks');
}

// ---------------------------------------------------------------------------
// Aggregation helpers
// ---------------------------------------------------------------------------

function countBy<T>(items: T[], keyFn: (item: T) => string): Record<string, number> {
  const counts: Record<string, number> = {};
  for (const item of items) {
    const key = keyFn(item);
    counts[key] = (counts[key] || 0) + 1;
  }
  return counts;
}

function formatCounts(counts: Record<string, number>): string {
  return Object.entries(counts)
    .sort((a, b) => b[1] - a[1])
    .map(([k, v]) => `${k} (${v})`)
    .join(', ');
}

function extractRepoName(repoUrl: string): string {
  const parts = repoUrl.replace(/\.git$/, '').split('/');
  return parts[parts.length - 1];
}

function mean(values: number[]): number {
  if (values.length === 0) return 0;
  return values.reduce((a, b) => a + b, 0) / values.length;
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

function main(): void {
  const tasksDir = getTasksDir();
  let manifests: CodingTaskManifest[];

  try {
    manifests = loadAllManifests(tasksDir);
  } catch (err) {
    console.error(`Error loading manifests: ${err}`);
    process.exit(1);
  }

  if (manifests.length === 0) {
    console.error('No task manifests found.');
    process.exit(1);
  }

  // Language counts (flatten arrays, capitalize first letter)
  const langCounts: Record<string, number> = {};
  for (const m of manifests) {
    for (const lang of m.language) {
      const display = lang.charAt(0).toUpperCase() + lang.slice(1);
      langCounts[display] = (langCounts[display] || 0) + 1;
    }
  }

  // Multi-language tasks get a combined label
  const langLabels: Record<string, number> = {};
  for (const m of manifests) {
    const label = m.language.map(l => l.charAt(0).toUpperCase() + l.slice(1)).join('+');
    langLabels[label] = (langLabels[label] || 0) + 1;
  }

  // Difficulty distribution
  const diffCounts = countBy(manifests, m => `L${m.difficulty}`);
  const diffDisplay = ['L1', 'L2', 'L3', 'L4']
    .map(d => `${d} (${diffCounts[d] || 0})`)
    .join(', ');

  // Repos
  const repos = [...new Set(manifests.map(m => extractRepoName(m.repo)))];

  // Token estimates
  const tokenEstimates = manifests
    .map(m => m.context_tokens_estimate ?? 0)
    .filter(t => t > 0);
  const avgTokens = mean(tokenEstimates);

  // Context file counts
  const contextCounts = manifests.map(m => m.context_files.length);
  const avgContextFiles = mean(contextCounts);

  // RFS scores
  const rfsScores = manifests.map(m => computeRFS(m).value);
  const meanRFS = mean(rfsScores);

  // Verification types
  const verTypes = countBy(manifests, m => m.verification.type);

  // Tags
  const allTags: Record<string, number> = {};
  for (const m of manifests) {
    for (const tag of m.metadata?.tags ?? []) {
      allTags[tag] = (allTags[tag] || 0) + 1;
    }
  }
  const topTags = Object.entries(allTags)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 5)
    .map(([t, c]) => `${t} (${c})`)
    .join(', ');

  // Print summary
  const lines = [
    '',
    'Long-Context Eval Dataset -- Summary',
    '====================================',
    `Total tasks:     ${manifests.length}`,
    `Languages:       ${formatCounts(langLabels)}`,
    `Difficulty:      ${diffDisplay}`,
    `Avg context:     ~${Math.round(avgTokens / 1000)}K tokens (${avgContextFiles.toFixed(1)} files avg)`,
    `Repos:           ${repos.join(', ')}`,
    `Verification:    ${formatCounts(verTypes)}`,
    '',
    'Metrics (static, from manifests):',
    `  Mean RFS:        ${meanRFS.toFixed(1)} (cross-component reasoning demand)`,
    `  RFS range:       ${Math.min(...rfsScores).toFixed(1)} - ${Math.max(...rfsScores).toFixed(1)}`,
    `  Context files:   ${Math.min(...contextCounts)} - ${Math.max(...contextCounts)} per task`,
    '',
    'Top tags:          ' + topTags,
    '',
    'Per-task breakdown:',
    '-'.repeat(80),
    padRow('Task ID', 'Diff', 'Lang', 'Files', 'Tokens', 'RFS'),
    '-'.repeat(80),
  ];

  for (let i = 0; i < manifests.length; i++) {
    const m = manifests[i];
    const rfs = rfsScores[i];
    lines.push(padRow(
      m.id,
      `L${m.difficulty}`,
      m.language.join('+'),
      String(m.context_files.length),
      m.context_tokens_estimate ? `~${Math.round(m.context_tokens_estimate / 1000)}K` : '?',
      rfs.toFixed(1),
    ));
  }

  lines.push('-'.repeat(80));
  lines.push('');

  console.log(lines.join('\n'));
}

function padRow(...cols: string[]): string {
  const widths = [45, 5, 12, 6, 8, 6];
  return cols.map((c, i) => c.padEnd(widths[i] || 10)).join('');
}

main();

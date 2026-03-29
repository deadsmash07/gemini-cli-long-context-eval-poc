/**
 * @license
 * Copyright 2026 Google LLC
 * SPDX-License-Identifier: Apache-2.0
 */

/**
 * CLI entry point for running long-context coding evaluations.
 *
 * Usage:
 *   npx tsx runner/run-eval.ts                    # dry-run (default)
 *   npx tsx runner/run-eval.ts --live             # actually spawn the agent
 *   npx tsx runner/run-eval.ts --live --parallel  # run tasks in parallel
 *   npx tsx runner/run-eval.ts --tasks schema/sample-tasks/
 *   npx tsx runner/run-eval.ts --model gemini-2.5-flash
 *   npx tsx runner/run-eval.ts --timeout 300000
 */

import * as fs from 'fs';
import * as path from 'path';
import {
  CodingTaskRunner,
  loadAllManifests,
  type CodingTaskManifest,
  type RunResult,
} from './coding-task-runner.js';
import { computeRFS } from './metrics.js';

// ---------------------------------------------------------------------------
// CLI arg parsing
// ---------------------------------------------------------------------------

interface CliArgs {
  tasksDir: string;
  live: boolean;
  parallel: boolean;
  model: string;
  timeoutMs: number;
  outputPath: string;
}

function parseCliArgs(): CliArgs {
  const argv = process.argv.slice(2);
  const args: CliArgs = {
    tasksDir: path.resolve(
      path.dirname(new URL(import.meta.url).pathname),
      '..', 'schema', 'sample-tasks',
    ),
    live: false,
    parallel: false,
    model: 'gemini-2.5-pro',
    timeoutMs: 10 * 60 * 1000,
    outputPath: path.resolve(
      path.dirname(new URL(import.meta.url).pathname),
      '..', 'results', 'latest.json',
    ),
  };

  for (let i = 0; i < argv.length; i++) {
    switch (argv[i]) {
      case '--tasks':
        args.tasksDir = path.resolve(argv[++i]);
        break;
      case '--live':
        args.live = true;
        break;
      case '--parallel':
        args.parallel = true;
        break;
      case '--model':
        args.model = argv[++i];
        break;
      case '--timeout':
        args.timeoutMs = parseInt(argv[++i], 10);
        break;
      case '--output':
        args.outputPath = path.resolve(argv[++i]);
        break;
      case '--help':
        printHelp();
        process.exit(0);
    }
  }

  return args;
}

function printHelp(): void {
  console.log(`
Usage: npx tsx runner/run-eval.ts [options]

Options:
  --tasks <dir>      Directory containing task manifest JSON files
                     (default: schema/sample-tasks/)
  --live             Run the agent for real (default: dry-run mode)
  --parallel         Run tasks in parallel (only with --live)
  --model <name>     Model to test (default: gemini-2.5-pro)
  --timeout <ms>     Per-task timeout in ms (default: 600000)
  --output <path>    Output JSON path (default: results/latest.json)
  --help             Show this help message
`);
}

// ---------------------------------------------------------------------------
// Result formatting
// ---------------------------------------------------------------------------

function printResultsTable(results: RunResult[], manifests: CodingTaskManifest[]): void {
  const header = padRow('Task', 'Status', 'Time', 'Calls', 'PES', 'RFS', 'Failure');
  console.log('');
  console.log('Evaluation Results');
  console.log('='.repeat(95));
  console.log(header);
  console.log('-'.repeat(95));

  for (const r of results) {
    const status = r.passed ? 'PASS' : 'FAIL';
    const time = r.durationMs > 0 ? `${(r.durationMs / 1000).toFixed(1)}s` : '-';
    const calls = r.metrics.totalToolCalls > 0 ? String(r.metrics.totalToolCalls) : '-';
    const pes = r.metrics.pes > 0 ? r.metrics.pes.toFixed(2) : '-';
    const rfs = r.metrics.rfs.toFixed(1);
    const failure = r.failure ? r.failure.mode : '-';

    console.log(padRow(r.taskId, status, time, calls, pes, rfs, failure));
  }

  console.log('-'.repeat(95));

  // Summary row
  const passCount = results.filter(r => r.passed).length;
  const totalTime = results.reduce((s, r) => s + r.durationMs, 0);
  console.log(`\nPassed: ${passCount}/${results.length}`);
  if (totalTime > 0) {
    console.log(`Total time: ${(totalTime / 1000).toFixed(1)}s`);
  }
  console.log('');
}

function padRow(...cols: string[]): string {
  const widths = [45, 7, 8, 7, 7, 7, 20];
  return cols.map((c, i) => c.padEnd(widths[i] || 10)).join('');
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

async function main(): Promise<void> {
  const args = parseCliArgs();

  console.log('Long-Context Coding Eval Runner');
  console.log(`Mode: ${args.live ? 'LIVE' : 'DRY-RUN'}`);
  console.log(`Tasks: ${args.tasksDir}`);
  console.log(`Model: ${args.model}`);
  if (args.live) {
    console.log(`Timeout: ${args.timeoutMs}ms per task`);
    console.log(`Parallel: ${args.parallel}`);
  }
  console.log('');

  // Load manifests
  let manifests: CodingTaskManifest[];
  try {
    manifests = loadAllManifests(args.tasksDir);
    console.log(`Loaded ${manifests.length} task manifest(s)`);
  } catch (err) {
    console.error(`Failed to load manifests: ${err}`);
    process.exit(1);
  }

  if (manifests.length === 0) {
    console.error('No task manifests found. Nothing to do.');
    process.exit(1);
  }

  // In dry-run mode, compute static metrics and show what would happen
  if (!args.live) {
    console.log('');
    console.log('[dry-run] Validating manifests and computing static metrics...');
    console.log('');

    const results: RunResult[] = [];
    for (const m of manifests) {
      const runner = new CodingTaskRunner(m, {
        modelsToTest: [args.model],
        dryRun: true,
      });
      const result = runner.dryRun();
      results.push(result);

      const rfs = computeRFS(m);
      console.log(
        `  ${m.id}  L${m.difficulty}  ${m.language.join('+')}  ` +
        `${m.context_files.length} files  ~${Math.round((m.context_tokens_estimate ?? 0) / 1000)}K tokens  ` +
        `RFS=${rfs.value.toFixed(1)} (${rfs.rating})`,
      );
    }

    printResultsTable(results, manifests);
    saveResults(results, args.outputPath);
    console.log('[dry-run] To run for real, add the --live flag.');
    return;
  }

  // Live mode
  const results: RunResult[] = [];

  if (args.parallel) {
    console.log(`Running ${manifests.length} tasks in parallel...`);
    const promises = manifests.map(m => {
      const runner = new CodingTaskRunner(m, {
        modelsToTest: [args.model],
        timeoutMs: args.timeoutMs,
      });
      return runner.run().then(r => r[0]);
    });
    const settled = await Promise.allSettled(promises);
    for (const s of settled) {
      if (s.status === 'fulfilled') {
        results.push(s.value);
      } else {
        console.error(`Task failed: ${s.reason}`);
      }
    }
  } else {
    console.log(`Running ${manifests.length} tasks sequentially...`);
    for (const m of manifests) {
      const runner = new CodingTaskRunner(m, {
        modelsToTest: [args.model],
        timeoutMs: args.timeoutMs,
      });
      try {
        const taskResults = await runner.run();
        results.push(...taskResults);
      } catch (err) {
        console.error(`[${m.id}] Runner error: ${err}`);
      }
    }
  }

  printResultsTable(results, manifests);
  saveResults(results, args.outputPath);
}

function saveResults(results: RunResult[], outputPath: string): void {
  const outputDir = path.dirname(outputPath);
  fs.mkdirSync(outputDir, { recursive: true });

  const report = {
    generatedAt: new Date().toISOString(),
    taskCount: results.length,
    passCount: results.filter(r => r.passed).length,
    results,
  };

  fs.writeFileSync(outputPath, JSON.stringify(report, null, 2));
  console.log(`Results saved to ${outputPath}`);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});

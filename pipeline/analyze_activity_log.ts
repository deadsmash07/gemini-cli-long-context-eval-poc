/**
 * @license
 * Copyright 2026 Google LLC
 * SPDX-License-Identifier: Apache-2.0
 */

/**
 * Parse Gemini CLI JSONL activity logs and compute evaluation metrics.
 *
 * Reads activity log files from a directory, extracts tool-call data,
 * and produces a JSON report with per-task and aggregate metrics.
 *
 * Usage:
 *   npx ts-node analyze_activity_log.ts --logs ./logs --manifests ./tasks --output report.json
 */

import * as fs from 'fs';
import * as path from 'path';
import * as readline from 'readline';

interface ToolCall {
  type: string;
  timestamp?: string;
  file?: string;
}

interface TaskMetrics {
  logFile: string;
  totalToolCalls: number;
  toolCallBreakdown: Record<string, number>;
  uniqueFilesRead: number;
  uniqueFilesEdited: number;
  timeToFirstEdit: number; // tool calls before first edit
  explorationRatio: number; // reads / (reads + edits)
}

interface AggregateMetrics {
  taskCount: number;
  meanToolCalls: number;
  medianToolCalls: number;
  meanToolEfficiency: number; // files_edited / total_tool_calls
  meanContextCoverage: number | null; // files_read / context_files_count
}

interface Report {
  generatedAt: string;
  tasks: TaskMetrics[];
  aggregate: AggregateMetrics;
}

const READ_TOOLS = new Set(['read_file', 'read_many_files', 'grep_search', 'glob']);
const EDIT_TOOLS = new Set(['edit_file', 'write_file', 'write_new_file']);

function parseArgs(argv: string[]): {
  logsDir: string;
  manifestsDir: string | null;
  output: string;
} {
  let logsDir = './logs';
  let manifestsDir: string | null = null;
  let output = 'report.json';

  for (let i = 2; i < argv.length; i++) {
    switch (argv[i]) {
      case '--logs':
        logsDir = argv[++i];
        break;
      case '--manifests':
        manifestsDir = argv[++i];
        break;
      case '--output':
        output = argv[++i];
        break;
    }
  }
  return { logsDir, manifestsDir, output };
}

async function parseLogFile(filePath: string): Promise<ToolCall[]> {
  const calls: ToolCall[] = [];
  const stream = fs.createReadStream(filePath, { encoding: 'utf-8' });
  const rl = readline.createInterface({ input: stream, crlfDelay: Infinity });

  for await (const line of rl) {
    if (!line.trim()) continue;
    try {
      const entry = JSON.parse(line);
      if (entry.type === 'tool_call' || entry.toolName || entry.tool_name) {
        calls.push({
          type: entry.toolName || entry.tool_name || entry.name || 'unknown',
          timestamp: entry.timestamp || entry.ts,
          file: entry.filePath || entry.file_path || entry.args?.file_path,
        });
      }
    } catch {
      // skip malformed lines
    }
  }
  return calls;
}

function computeTaskMetrics(logFile: string, calls: ToolCall[]): TaskMetrics {
  const breakdown: Record<string, number> = {};
  const filesRead = new Set<string>();
  const filesEdited = new Set<string>();
  let firstEditIndex = -1;

  for (let i = 0; i < calls.length; i++) {
    const call = calls[i];
    breakdown[call.type] = (breakdown[call.type] || 0) + 1;

    if (READ_TOOLS.has(call.type) && call.file) {
      filesRead.add(call.file);
    }
    if (EDIT_TOOLS.has(call.type)) {
      if (firstEditIndex === -1) firstEditIndex = i;
      if (call.file) filesEdited.add(call.file);
    }
  }

  const readCount = calls.filter((c) => READ_TOOLS.has(c.type)).length;
  const editCount = calls.filter((c) => EDIT_TOOLS.has(c.type)).length;
  const denom = readCount + editCount;

  return {
    logFile: path.basename(logFile),
    totalToolCalls: calls.length,
    toolCallBreakdown: breakdown,
    uniqueFilesRead: filesRead.size,
    uniqueFilesEdited: filesEdited.size,
    timeToFirstEdit: firstEditIndex === -1 ? calls.length : firstEditIndex,
    explorationRatio: denom > 0 ? readCount / denom : 0,
  };
}

function median(values: number[]): number {
  if (values.length === 0) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 === 0
    ? (sorted[mid - 1] + sorted[mid]) / 2
    : sorted[mid];
}

function computeAggregate(
  tasks: TaskMetrics[],
  contextFileCounts: Map<string, number>,
): AggregateMetrics {
  const n = tasks.length;
  if (n === 0) {
    return {
      taskCount: 0,
      meanToolCalls: 0,
      medianToolCalls: 0,
      meanToolEfficiency: 0,
      meanContextCoverage: null,
    };
  }

  const toolCallCounts = tasks.map((t) => t.totalToolCalls);
  const efficiencies = tasks.map((t) =>
    t.totalToolCalls > 0 ? t.uniqueFilesEdited / t.totalToolCalls : 0,
  );

  let coverageSum = 0;
  let coverageCount = 0;
  for (const task of tasks) {
    const baseName = task.logFile.replace(/\.jsonl$/, '');
    const contextCount = contextFileCounts.get(baseName);
    if (contextCount && contextCount > 0) {
      coverageSum += task.uniqueFilesRead / contextCount;
      coverageCount++;
    }
  }

  return {
    taskCount: n,
    meanToolCalls: toolCallCounts.reduce((a, b) => a + b, 0) / n,
    medianToolCalls: median(toolCallCounts),
    meanToolEfficiency: efficiencies.reduce((a, b) => a + b, 0) / n,
    meanContextCoverage:
      coverageCount > 0 ? coverageSum / coverageCount : null,
  };
}

function loadContextFileCounts(
  manifestsDir: string | null,
): Map<string, number> {
  const counts = new Map<string, number>();
  if (!manifestsDir || !fs.existsSync(manifestsDir)) return counts;

  const files = fs
    .readdirSync(manifestsDir)
    .filter((f) => f.endsWith('.json'));

  for (const file of files) {
    try {
      const data = JSON.parse(
        fs.readFileSync(path.join(manifestsDir, file), 'utf-8'),
      );
      const id = data.id || file.replace(/\.json$/, '');
      counts.set(id, (data.context_files || []).length);
    } catch {
      // skip unparseable manifests
    }
  }
  return counts;
}

async function main(): Promise<void> {
  const { logsDir, manifestsDir, output } = parseArgs(process.argv);

  if (!fs.existsSync(logsDir)) {
    console.error(`Logs directory not found: ${logsDir}`);
    process.exit(1);
  }

  const logFiles = fs
    .readdirSync(logsDir)
    .filter((f) => f.endsWith('.jsonl'))
    .map((f) => path.join(logsDir, f));

  if (logFiles.length === 0) {
    console.error(`No .jsonl files found in ${logsDir}`);
    process.exit(1);
  }

  console.error(`Processing ${logFiles.length} log file(s)...`);

  const tasks: TaskMetrics[] = [];
  for (const logFile of logFiles) {
    const calls = await parseLogFile(logFile);
    tasks.push(computeTaskMetrics(logFile, calls));
  }

  const contextCounts = loadContextFileCounts(manifestsDir);
  const aggregate = computeAggregate(tasks, contextCounts);

  const report: Report = {
    generatedAt: new Date().toISOString(),
    tasks,
    aggregate,
  };

  fs.writeFileSync(output, JSON.stringify(report, null, 2));
  console.error(`Report written to ${output}`);

  // Print summary to stdout
  console.log(JSON.stringify(aggregate, null, 2));
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});

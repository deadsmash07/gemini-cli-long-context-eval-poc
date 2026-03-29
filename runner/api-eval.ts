/**
 * @license
 * Copyright 2026 Google LLC
 * SPDX-License-Identifier: Apache-2.0
 */

/**
 * Lightweight Gemini API-based evaluation runner.
 *
 * Instead of spawning the full Gemini CLI binary, this evaluator:
 *   1. Clones the target repo at the pinned commit SHA
 *   2. Reads the context files listed in the manifest
 *   3. Sends the file contents + task prompt to the Gemini REST API
 *   4. Analyzes the model's response to check file identification accuracy
 *
 * This demonstrates the end-to-end pipeline with real model output.
 *
 * Usage:
 *   GEMINI_API_KEY=... npx tsx runner/api-eval.ts
 *   GEMINI_API_KEY=... npx tsx runner/api-eval.ts --model gemini-2.5-pro
 */

import * as fs from 'fs';
import * as path from 'path';
import * as os from 'os';
import { execFileSync } from 'child_process';
import { loadAllManifests, type CodingTaskManifest } from './coding-task-runner.js';
import { computeRFS, type MetricResult } from './metrics.js';

// ---------------------------------------------------------------------------
// Config
// ---------------------------------------------------------------------------

const API_BASE = 'https://generativelanguage.googleapis.com/v1beta/models';
const DEFAULT_MODEL = 'gemini-2.5-flash';
const CACHE_DIR = path.join(os.homedir(), '.cache', 'coding-task-evals', 'repos');

// Tasks to evaluate (L2, smallest context — fast and cheap)
const TARGET_TASKS = [
  'task-002-express-render-null-options',
  'task-001-fastapi-swagger-ui-escaping',
  'task-004-flask-trusted-hosts-config',
];

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface ApiEvalResult {
  taskId: string;
  model: string;
  durationMs: number;
  filesIdentified: string[];
  filesExpected: string[];
  filesCorrect: string[];
  filesMissed: string[];
  accuracy: number;
  rfs: number;
  responseTokens: number;
  reasoning: string; // first 500 chars of model response
}

// ---------------------------------------------------------------------------
// Git helpers
// ---------------------------------------------------------------------------

function gitExec(args: string[], opts?: { cwd?: string; timeout?: number }): string {
  return execFileSync('git', args, {
    cwd: opts?.cwd,
    timeout: opts?.timeout ?? 120_000,
    encoding: 'utf-8',
    stdio: ['pipe', 'pipe', 'pipe'],
  }).trim();
}

function ensureRepo(manifest: CodingTaskManifest): string {
  fs.mkdirSync(CACHE_DIR, { recursive: true });

  const parts = manifest.repo.replace(/\.git$/, '').split('/');
  const slug = `${parts[parts.length - 2]}-${parts[parts.length - 1]}`;
  const bareDir = path.join(CACHE_DIR, `${slug}.git`);

  if (!fs.existsSync(bareDir)) {
    console.error(`  [clone] Cloning ${manifest.repo} ...`);
    gitExec(['clone', '--bare', '--no-tags', manifest.repo, bareDir]);
  }

  // Ensure the target SHA is available
  try {
    gitExec(['cat-file', '-t', manifest.commit_sha], { cwd: bareDir });
  } catch {
    console.error(`  [fetch] Fetching SHA ${manifest.commit_sha.slice(0, 12)} ...`);
    gitExec(['fetch', 'origin', manifest.commit_sha], { cwd: bareDir });
  }

  return bareDir;
}

function createWorktree(bareDir: string, manifest: CodingTaskManifest): string {
  const dir = path.join(os.tmpdir(), 'api-eval', manifest.id, `run-${Date.now()}`);
  fs.mkdirSync(dir, { recursive: true });
  gitExec(['worktree', 'add', '--detach', dir, manifest.commit_sha], { cwd: bareDir });
  return dir;
}

function cleanupWorktree(bareDir: string, dir: string): void {
  try {
    gitExec(['worktree', 'remove', '--force', dir], { cwd: bareDir });
  } catch { /* best-effort */ }
  try {
    fs.rmSync(dir, { recursive: true, force: true });
  } catch { /* best-effort */ }
}

// ---------------------------------------------------------------------------
// Read context files from the checked-out repo
// ---------------------------------------------------------------------------

function readContextFiles(worktreeDir: string, files: string[]): Record<string, string> {
  const result: Record<string, string> = {};
  for (const f of files) {
    const fullPath = path.join(worktreeDir, f);
    if (fs.existsSync(fullPath)) {
      const content = fs.readFileSync(fullPath, 'utf-8');
      // Limit each file to ~4000 chars to stay within token budget
      result[f] = content.length > 4000 ? content.slice(0, 4000) + '\n... (truncated)' : content;
    } else {
      result[f] = '(file not found at this commit)';
    }
  }
  return result;
}

// ---------------------------------------------------------------------------
// Gemini API call
// ---------------------------------------------------------------------------

async function callGeminiAPI(
  prompt: string,
  model: string,
  apiKey: string,
): Promise<{ text: string; tokenCount: number; durationMs: number }> {
  const url = `${API_BASE}/${model}:generateContent?key=${apiKey}`;

  const start = Date.now();
  const response = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      contents: [{ parts: [{ text: prompt }] }],
      generationConfig: {
        temperature: 0,
        maxOutputTokens: 8192,
      },
    }),
  });

  const durationMs = Date.now() - start;

  if (!response.ok) {
    const error = await response.text();
    throw new Error(`API error ${response.status}: ${error}`);
  }

  const data = await response.json() as {
    candidates?: Array<{ content?: { parts?: Array<{ text?: string }> } }>;
    usageMetadata?: { candidatesTokenCount?: number; totalTokenCount?: number };
  };

  const text = data.candidates?.[0]?.content?.parts?.[0]?.text ?? '';
  const tokenCount = data.usageMetadata?.totalTokenCount ?? 0;

  return { text, tokenCount, durationMs };
}

// ---------------------------------------------------------------------------
// Build the evaluation prompt
// ---------------------------------------------------------------------------

function buildPrompt(manifest: CodingTaskManifest, contextFiles: Record<string, string>): string {
  let prompt = `You are a senior software engineer. You need to analyze code and identify which files need to be modified to fix a bug or implement a feature.

## Repository: ${manifest.repo}
## Language(s): ${manifest.language.join(', ')}

## Context Files

`;

  for (const [filePath, content] of Object.entries(contextFiles)) {
    prompt += `### ${filePath}\n\`\`\`\n${content}\n\`\`\`\n\n`;
  }

  prompt += `## Task

${manifest.prompt}

## Instructions

1. Analyze the code above and identify the root cause
2. List the EXACT file paths that need to be modified (use the paths shown above)
3. For each file, describe what specific changes are needed
4. Provide the actual code changes

Start your response with "FILES TO MODIFY:" followed by a comma-separated list of file paths.
Then explain your reasoning and provide the changes.`;

  return prompt;
}

// ---------------------------------------------------------------------------
// Parse model response
// ---------------------------------------------------------------------------

function extractFilesFromResponse(response: string, contextFiles: string[]): string[] {
  const files = new Set<string>();

  // Try to find "FILES TO MODIFY:" header
  const headerMatch = response.match(/FILES TO MODIFY:\s*(.+?)(?:\n|$)/i);
  if (headerMatch) {
    const fileList = headerMatch[1].split(/[,\n]/).map(f => f.trim().replace(/^`|`$/g, ''));
    for (const f of fileList) {
      if (f && contextFiles.some(cf => cf === f || f.endsWith(cf) || cf.endsWith(f))) {
        // Normalize to the manifest's file path
        const match = contextFiles.find(cf => cf === f || f.endsWith(cf) || cf.endsWith(f));
        if (match) files.add(match);
      }
    }
  }

  // Also scan for file paths mentioned anywhere in the response
  for (const contextFile of contextFiles) {
    const basename = path.basename(contextFile);
    if (response.includes(contextFile) || response.includes(basename)) {
      files.add(contextFile);
    }
  }

  return [...files];
}

// ---------------------------------------------------------------------------
// Main evaluation loop
// ---------------------------------------------------------------------------

function loadEnvFile(): void {
  const envPath = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..', '.env');
  if (fs.existsSync(envPath)) {
    const lines = fs.readFileSync(envPath, 'utf-8').split('\n');
    for (const line of lines) {
      const match = line.match(/^([A-Z_]+)=(.+)$/);
      if (match && !process.env[match[1]]) {
        process.env[match[1]] = match[2].trim();
      }
    }
  }
}

async function runApiEval(model: string): Promise<void> {
  loadEnvFile();
  const apiKey = process.env['GEMINI_API_KEY'];
  if (!apiKey) {
    console.error('Error: GEMINI_API_KEY environment variable is required');
    console.error('Set it in .env file or export GEMINI_API_KEY=...');
    process.exit(1);
  }

  const tasksDir = path.resolve(
    path.dirname(new URL(import.meta.url).pathname),
    '..', 'schema', 'sample-tasks',
  );

  const allManifests = loadAllManifests(tasksDir);
  const manifests = allManifests.filter(m => TARGET_TASKS.includes(m.id));

  if (manifests.length === 0) {
    console.error('No matching tasks found. Available:', allManifests.map(m => m.id).join(', '));
    process.exit(1);
  }

  console.log(`\nGemini API Evaluation`);
  console.log(`Model: ${model}`);
  console.log(`Tasks: ${manifests.length}\n`);

  const results: ApiEvalResult[] = [];

  for (const manifest of manifests) {
    console.log(`\n--- ${manifest.id} (${manifest.language.join(', ')}, L${manifest.difficulty}) ---`);

    // Step 1: Clone and checkout
    console.error('  Setting up repo...');
    const bareDir = ensureRepo(manifest);
    const worktreeDir = createWorktree(bareDir, manifest);

    try {
      // Step 2: Read context files
      console.error('  Reading context files...');
      const contextFiles = readContextFiles(worktreeDir, manifest.context_files);
      const readableFiles = Object.keys(contextFiles).filter(
        f => contextFiles[f] !== '(file not found at this commit)'
      );
      console.error(`  Read ${readableFiles.length}/${manifest.context_files.length} context files`);

      // Step 3: Build prompt and call API
      const prompt = buildPrompt(manifest, contextFiles);
      console.error(`  Calling ${model} (prompt ~${Math.round(prompt.length / 4)} tokens)...`);

      const { text, tokenCount, durationMs } = await callGeminiAPI(prompt, model, apiKey);
      console.error(`  Response in ${(durationMs / 1000).toFixed(1)}s (${tokenCount} tokens)`);

      // Step 4: Analyze response
      const filesIdentified = extractFilesFromResponse(text, manifest.context_files);
      const expected = manifest.verification.expected_files_changed;
      const correct = filesIdentified.filter(f => expected.includes(f));
      const missed = expected.filter(f => !filesIdentified.includes(f));
      const accuracy = expected.length > 0 ? correct.length / expected.length : 0;

      const result: ApiEvalResult = {
        taskId: manifest.id,
        model,
        durationMs,
        filesIdentified,
        filesExpected: expected,
        filesCorrect: correct,
        filesMissed: missed,
        accuracy,
        rfs: (computeRFS(manifest) as MetricResult).value,
        responseTokens: tokenCount,
        reasoning: text.slice(0, 500),
      };

      results.push(result);

      // Print result
      console.log(`  Files identified: ${filesIdentified.join(', ') || '(none)'}`);
      console.log(`  Files expected:   ${expected.join(', ')}`);
      console.log(`  Accuracy:         ${correct.length}/${expected.length} (${(accuracy * 100).toFixed(0)}%)`);
      console.log(`  Response time:    ${(durationMs / 1000).toFixed(1)}s`);
      console.log(`  RFS:              ${result.rfs}`);

    } finally {
      cleanupWorktree(bareDir, worktreeDir);
    }
  }

  // Print summary table
  console.log(`\n${'='.repeat(90)}`);
  console.log(`Gemini API Evaluation Results — ${model}`);
  console.log(`${'='.repeat(90)}`);

  const header = 'Task                                       Accuracy  Time     RFS   Tokens';
  console.log(header);
  console.log('-'.repeat(90));

  for (const r of results) {
    const id = r.taskId.padEnd(43);
    const acc = `${r.filesCorrect.length}/${r.filesExpected.length} (${(r.accuracy * 100).toFixed(0)}%)`.padEnd(10);
    const time = `${(r.durationMs / 1000).toFixed(1)}s`.padEnd(9);
    const rfs = String(r.rfs).padEnd(6);
    console.log(`${id}${acc}${time}${rfs}${r.responseTokens}`);
  }

  console.log('-'.repeat(90));
  const avgAccuracy = results.reduce((sum, r) => sum + r.accuracy, 0) / results.length;
  const avgTime = results.reduce((sum, r) => sum + r.durationMs, 0) / results.length;
  console.log(`Average accuracy: ${(avgAccuracy * 100).toFixed(0)}%  |  Avg response time: ${(avgTime / 1000).toFixed(1)}s`);
  console.log(`${'='.repeat(90)}\n`);

  // Save results
  const outputDir = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..', 'results');
  fs.mkdirSync(outputDir, { recursive: true });
  const outputPath = path.join(outputDir, 'api-eval-results.json');
  fs.writeFileSync(outputPath, JSON.stringify({ model, timestamp: new Date().toISOString(), results }, null, 2));
  console.log(`Results saved to ${outputPath}`);
}

// ---------------------------------------------------------------------------
// CLI
// ---------------------------------------------------------------------------

const argv = process.argv.slice(2);
let model = DEFAULT_MODEL;
for (let i = 0; i < argv.length; i++) {
  if (argv[i] === '--model' && argv[i + 1]) model = argv[++i];
}

runApiEval(model).catch(err => {
  console.error('Fatal error:', err);
  process.exit(1);
});

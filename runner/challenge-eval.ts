/**
 * @license
 * Copyright 2026 Google LLC
 * SPDX-License-Identifier: Apache-2.0
 */

/**
 * Evaluates challenge tasks (Tier 2) by:
 *   1. Reading the task instruction and environment files
 *   2. Sending them to the Gemini API to generate a solution
 *   3. Building the Docker container
 *   4. Injecting the model's solution into the container
 *   5. Running the test suite
 *   6. Reporting pass/fail with details
 *
 * Usage:
 *   GEMINI_API_KEY=... npx tsx runner/challenge-eval.ts
 *   GEMINI_API_KEY=... npx tsx runner/challenge-eval.ts --model gemini-2.5-pro
 *   GEMINI_API_KEY=... npx tsx runner/challenge-eval.ts --task git-hook-generator
 *
 * Security: All shell commands use execFileSync with array args where possible.
 * The few cases using execSync operate on developer-authored manifest data only.
 */

import * as fs from 'fs';
import * as path from 'path';
import { execFileSync } from 'child_process';

// ---------------------------------------------------------------------------
// Config
// ---------------------------------------------------------------------------

const API_BASE = 'https://generativelanguage.googleapis.com/v1beta/models';
const DEFAULT_MODEL = 'gemini-2.5-flash';
const CHALLENGE_DIR = path.resolve(
  path.dirname(new URL(import.meta.url).pathname),
  '..', 'challenge-tasks',
);

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface ChallengeResult {
  task: string;
  model: string;
  difficulty: string;
  apiDurationMs: number;
  apiTokens: number;
  dockerBuild: 'pass' | 'fail';
  testsRun: boolean;
  testsPassed: number;
  testsFailed: number;
  testsTotal: number;
  passRate: number;
  status: 'pass' | 'partial' | 'fail' | 'error';
  error?: string;
  solutionLength: number;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function loadEnvFile(): void {
  const envPath = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..', '.env');
  if (fs.existsSync(envPath)) {
    for (const line of fs.readFileSync(envPath, 'utf-8').split('\n')) {
      const match = line.match(/^([A-Z_]+)=(.+)$/);
      if (match && !process.env[match[1]]) {
        process.env[match[1]] = match[2].trim();
      }
    }
  }
}

function parseToml(content: string): Record<string, any> {
  const result: Record<string, any> = {};
  let currentSection = result;

  for (const line of content.split('\n')) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith('#')) continue;

    const sectionMatch = trimmed.match(/^\[(.+)\]$/);
    if (sectionMatch) {
      const parts = sectionMatch[1].split('.');
      let obj = result;
      for (const part of parts) {
        if (!obj[part]) obj[part] = {};
        obj = obj[part];
      }
      currentSection = obj;
      continue;
    }

    const kvMatch = trimmed.match(/^(\w+)\s*=\s*(.+)$/);
    if (kvMatch) {
      let value: any = kvMatch[2].trim();
      if (value === 'true') value = true;
      else if (value === 'false') value = false;
      else if (value.match(/^[\d.]+$/) && !isNaN(Number(value))) value = Number(value);
      else if (value.startsWith('"') && value.endsWith('"')) value = value.slice(1, -1);
      else if (value.startsWith('[')) {
        try { value = JSON.parse(value.replace(/'/g, '"')); } catch { /* keep string */ }
      }
      currentSection[kvMatch[1]] = value;
    }
  }
  return result;
}

function readTaskFiles(taskDir: string): { instruction: string; envFiles: Record<string, string> } {
  const instruction = fs.readFileSync(path.join(taskDir, 'instruction.md'), 'utf-8');
  const envFiles: Record<string, string> = {};

  const envDir = path.join(taskDir, 'environment');
  if (fs.existsSync(envDir)) {
    const walk = (dir: string, prefix: string) => {
      for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
        const rel = prefix ? `${prefix}/${entry.name}` : entry.name;
        if (entry.isDirectory()) {
          walk(path.join(dir, entry.name), rel);
        } else if (!entry.name.startsWith('.')) {
          const content = fs.readFileSync(path.join(dir, entry.name), 'utf-8');
          if (content.length < 5000) {
            envFiles[rel] = content;
          }
        }
      }
    };
    walk(envDir, '');
  }
  return { instruction, envFiles };
}

// ---------------------------------------------------------------------------
// Gemini API
// ---------------------------------------------------------------------------

async function callGemini(
  prompt: string,
  model: string,
  apiKey: string,
): Promise<{ text: string; tokens: number; durationMs: number }> {
  const url = `${API_BASE}/${model}:generateContent?key=${apiKey}`;
  const start = Date.now();

  const resp = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      contents: [{ parts: [{ text: prompt }] }],
      generationConfig: { temperature: 0, maxOutputTokens: 16384 },
    }),
  });

  const durationMs = Date.now() - start;

  if (!resp.ok) {
    const err = await resp.text();
    throw new Error(`API ${resp.status}: ${err.slice(0, 200)}`);
  }

  const data = await resp.json() as any;
  const text = data.candidates?.[0]?.content?.parts?.[0]?.text ?? '';
  const tokens = data.usageMetadata?.totalTokenCount ?? 0;

  return { text, tokens, durationMs };
}

// ---------------------------------------------------------------------------
// Docker execution (uses execFileSync for safety)
// ---------------------------------------------------------------------------

function buildDocker(taskDir: string, tag: string): boolean {
  try {
    execFileSync('docker', ['build', '-t', tag, 'environment/'], {
      cwd: taskDir,
      timeout: 120_000,
      stdio: ['pipe', 'pipe', 'pipe'],
    });
    return true;
  } catch (e: any) {
    console.error(`  Docker build failed: ${(e.stderr?.toString() || e.message).slice(0, 200)}`);
    return false;
  }
}

function extractSolutionScript(modelResponse: string): string {
  const bashMatch = modelResponse.match(/```(?:bash|sh)\n([\s\S]*?)```/);
  if (bashMatch) return bashMatch[1];

  const pythonMatch = modelResponse.match(/```python\n([\s\S]*?)```/);
  if (pythonMatch) return `cat > /tmp/solution.py << 'PYEOF'\n${pythonMatch[1]}\nPYEOF\npython3 /tmp/solution.py`;

  const anyCodeMatch = modelResponse.match(/```\n([\s\S]*?)```/);
  if (anyCodeMatch) return anyCodeMatch[1];

  return modelResponse;
}

function runTests(tag: string, taskDir: string, solutionScript: string): {
  passed: number; failed: number; total: number; output: string;
} {
  const tmpSolution = path.join('/tmp', `challenge-solution-${Date.now()}.sh`);
  fs.writeFileSync(tmpSolution, solutionScript, { mode: 0o755 });

  const testsDir = path.join(taskDir, 'tests');

  try {
    // Run solution then tests inside Docker
    const output = execFileSync('docker', [
      'run', '--rm',
      '-v', `${tmpSolution}:/tmp/solution.sh:ro`,
      '-v', `${testsDir}:/tests:ro`,
      tag,
      'bash', '-c',
      'bash /tmp/solution.sh 2>/dev/null; cd /tests && pytest test_*.py -v --tb=short 2>&1 || true',
    ], {
      timeout: 180_000,
      encoding: 'utf-8',
      stdio: ['pipe', 'pipe', 'pipe'],
    });

    const passed = parseInt(output.match(/(\d+) passed/)?.[1] || '0');
    const failed = parseInt(output.match(/(\d+) failed/)?.[1] || '0')
      + parseInt(output.match(/(\d+) error/)?.[1] || '0');

    fs.unlinkSync(tmpSolution);
    return { passed, failed, total: passed + failed, output: output.slice(-1000) };
  } catch (e: any) {
    const output = (e.stdout?.toString?.() || '') + (e.stderr?.toString?.() || '');
    const passed = parseInt(output.match(/(\d+) passed/)?.[1] || '0');
    const failed = parseInt(output.match(/(\d+) failed/)?.[1] || '0')
      + parseInt(output.match(/(\d+) error/)?.[1] || '0');

    try { fs.unlinkSync(tmpSolution); } catch { /* ok */ }
    return { passed, failed, total: passed + failed, output: output.slice(-1000) };
  }
}

// ---------------------------------------------------------------------------
// Build prompt
// ---------------------------------------------------------------------------

function buildPrompt(instruction: string, envFiles: Record<string, string>): string {
  let prompt = `You are a senior software engineer. Solve the following coding task that runs inside a Docker container (Python 3.11 + pytest).

## Task

${instruction}

## Environment Files

These files exist in the container:

`;

  for (const [filePath, content] of Object.entries(envFiles)) {
    if (filePath === 'Dockerfile' || filePath === 'docker-compose.yaml') continue;
    prompt += `### ${filePath}\n\`\`\`\n${content}\n\`\`\`\n\n`;
  }

  prompt += `## Output Format

Write a complete bash script that creates or modifies files to make all tests pass.
Use heredocs to write files: cat << 'EOF' > /path/to/file
All code must work in the Docker container (Python 3.11, pytest, git available).

Output ONLY a single \`\`\`bash code block. No explanation.`;

  return prompt;
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

async function main(): Promise<void> {
  loadEnvFile();
  const apiKey = process.env['GEMINI_API_KEY'];
  if (!apiKey) {
    console.error('Error: GEMINI_API_KEY required in .env');
    process.exit(1);
  }

  const argv = process.argv.slice(2);
  let model = DEFAULT_MODEL;
  let taskFilter: string | null = null;
  for (let i = 0; i < argv.length; i++) {
    if (argv[i] === '--model' && argv[i + 1]) model = argv[++i];
    if (argv[i] === '--task' && argv[i + 1]) taskFilter = argv[++i];
  }

  const taskDirs = fs.readdirSync(CHALLENGE_DIR)
    .filter(d => {
      const full = path.join(CHALLENGE_DIR, d);
      return fs.statSync(full).isDirectory() && fs.existsSync(path.join(full, 'task.toml'));
    })
    .filter(d => !taskFilter || d === taskFilter || d.includes(taskFilter))
    .sort();

  console.log(`\nChallenge Task Evaluation`);
  console.log(`Model: ${model}`);
  console.log(`Tasks: ${taskDirs.length}\n`);

  const results: ChallengeResult[] = [];

  for (const taskName of taskDirs) {
    const taskDir = path.join(CHALLENGE_DIR, taskName);
    console.log(`\n--- ${taskName} ---`);

    const toml = parseToml(fs.readFileSync(path.join(taskDir, 'task.toml'), 'utf-8'));
    const difficulty = toml.metadata?.difficulty || 'unknown';
    console.error(`  Difficulty: ${difficulty}`);

    const { instruction, envFiles } = readTaskFiles(taskDir);
    console.error(`  Instruction: ${instruction.length} chars, ${Object.keys(envFiles).length} env files`);

    const tag = `challenge-eval-${taskName}`;
    console.error(`  Building Docker image...`);
    const dockerOk = buildDocker(taskDir, tag);
    if (!dockerOk) {
      results.push({
        task: taskName, model, difficulty,
        apiDurationMs: 0, apiTokens: 0, dockerBuild: 'fail',
        testsRun: false, testsPassed: 0, testsFailed: 0, testsTotal: 0,
        passRate: 0, status: 'error', error: 'Docker build failed', solutionLength: 0,
      });
      continue;
    }

    const prompt = buildPrompt(instruction, envFiles);
    console.error(`  Calling ${model} (prompt ~${Math.round(prompt.length / 4)} tokens)...`);

    let apiResult;
    try {
      apiResult = await callGemini(prompt, model, apiKey);
    } catch (e: any) {
      console.error(`  API error: ${e.message}`);
      results.push({
        task: taskName, model, difficulty,
        apiDurationMs: 0, apiTokens: 0, dockerBuild: 'pass',
        testsRun: false, testsPassed: 0, testsFailed: 0, testsTotal: 0,
        passRate: 0, status: 'error', error: e.message, solutionLength: 0,
      });
      continue;
    }

    console.error(`  Response in ${(apiResult.durationMs / 1000).toFixed(1)}s (${apiResult.tokens} tokens)`);

    const solution = extractSolutionScript(apiResult.text);
    console.error(`  Solution: ${solution.length} chars`);
    console.error(`  Running tests in Docker...`);

    const testResult = runTests(tag, taskDir, solution);
    const passRate = testResult.total > 0 ? testResult.passed / testResult.total : 0;
    const status = passRate === 1 ? 'pass' : passRate > 0 ? 'partial' : 'fail';

    console.log(`  Tests: ${testResult.passed}/${testResult.total} passed (${(passRate * 100).toFixed(0)}%)`);
    console.log(`  Status: ${status.toUpperCase()}`);

    results.push({
      task: taskName, model, difficulty,
      apiDurationMs: apiResult.durationMs, apiTokens: apiResult.tokens,
      dockerBuild: 'pass', testsRun: true,
      testsPassed: testResult.passed, testsFailed: testResult.failed,
      testsTotal: testResult.total, passRate, status,
      solutionLength: solution.length,
    });

    // Cleanup
    try { execFileSync('docker', ['rmi', tag], { stdio: 'pipe' }); } catch { /* ok */ }
  }

  // Summary
  console.log(`\n${'='.repeat(100)}`);
  console.log(`Challenge Task Results - ${model}`);
  console.log(`${'='.repeat(100)}`);
  console.log('Task                                  Diff    Tests       Pass%   Time    Status');
  console.log('-'.repeat(100));

  for (const r of results) {
    const name = r.task.padEnd(38);
    const diff = r.difficulty.padEnd(8);
    const tests = r.testsRun ? `${r.testsPassed}/${r.testsTotal}`.padEnd(12) : 'N/A'.padEnd(12);
    const rate = r.testsRun ? `${(r.passRate * 100).toFixed(0)}%`.padEnd(8) : '-'.padEnd(8);
    const time = r.apiDurationMs > 0 ? `${(r.apiDurationMs / 1000).toFixed(0)}s`.padEnd(8) : '-'.padEnd(8);
    console.log(`${name}${diff}${tests}${rate}${time}${r.status.toUpperCase()}`);
  }

  console.log('-'.repeat(100));
  const ran = results.filter(r => r.testsRun);
  const avgPassRate = ran.length > 0 ? ran.reduce((s, r) => s + r.passRate, 0) / ran.length : 0;
  const fullPass = ran.filter(r => r.passRate === 1).length;
  console.log(`Full passes: ${fullPass}/${ran.length}  |  Avg test pass rate: ${(avgPassRate * 100).toFixed(0)}%`);
  console.log(`${'='.repeat(100)}\n`);

  // Save
  const outputDir = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..', 'results');
  fs.mkdirSync(outputDir, { recursive: true });
  const outputPath = path.join(outputDir, 'challenge-eval-results.json');
  fs.writeFileSync(outputPath, JSON.stringify({ model, timestamp: new Date().toISOString(), results }, null, 2));
  console.log(`Results saved to ${outputPath}`);
}

main().catch(err => { console.error('Fatal:', err); process.exit(1); });

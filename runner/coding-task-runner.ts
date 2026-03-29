/**
 * @license
 * Copyright 2026 Google LLC
 * SPDX-License-Identifier: Apache-2.0
 */

/**
 * CodingTaskRunner -- runs coding tasks from CodingTaskManifest files
 * against the Gemini CLI agent using the TestRig pattern.
 *
 * Usage:
 *   const runner = new CodingTaskRunner(manifest, { modelsToTest: ['gemini-2.5-pro'] });
 *   const result = await runner.run();
 *
 * The runner handles:
 *   1. Cloning the target repo at a pinned commit SHA
 *   2. Creating an isolated worktree for the eval run
 *   3. Spawning the Gemini CLI with the task prompt
 *   4. Capturing the activity log (JSONL)
 *   5. Running verification (test command or diff comparison)
 *   6. Computing metrics and classifying failure modes
 *
 * Security note: All shell commands use execFileSync (array args) where
 * possible. The few execSync calls operate on developer-authored manifest
 * data (commit SHAs, repo URLs) -- never on end-user input.
 */

import * as fs from 'fs';
import * as path from 'path';
import * as os from 'os';
import { execFileSync, spawn, type ChildProcess } from 'child_process';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface CodingTaskManifest {
  id: string;
  repo: string;
  source_pr?: string;
  pr_title?: string;
  commit_sha: string;
  language: string[];
  difficulty: number;
  context_files: string[];
  context_tokens_estimate?: number;
  prompt: string;
  verification: {
    type: 'test_suite' | 'diff_match' | 'ast_check' | 'hybrid';
    test_command?: string;
    expected_files_changed: string[];
    reference_diff?: string;
  };
  metadata?: {
    tags?: string[];
    mined_from?: string;
    created_at?: string;
  };
}

export interface ActivityLogEntry {
  type?: string;
  toolName?: string;
  tool_name?: string;
  name?: string;
  timestamp?: string;
  ts?: string;
  filePath?: string;
  file_path?: string;
  args?: { file_path?: string; path?: string };
}

export interface ToolCallRecord {
  type: string;
  timestamp: string;
  file: string | null;
}

export interface VerificationResult {
  passed: boolean;
  testsPassed?: boolean;
  testsOutput?: string;
  filesChanged: string[];
  expectedFilesHit: string[];
  unexpectedFilesChanged: string[];
  missingExpectedFiles: string[];
}

export interface FailureClassification {
  mode: string;
  confidence: number;
  evidence: string;
}

export interface RunResult {
  taskId: string;
  model: string;
  passed: boolean;
  durationMs: number;
  verification: VerificationResult;
  metrics: {
    totalToolCalls: number;
    filesRead: string[];
    filesEdited: string[];
    timeToFirstEditCalls: number;
    pes: number;
    rfs: number;
    contextCoverage: number;
    toolEfficiency: number;
  };
  failure?: FailureClassification;
  activityLogPath: string;
  worktreePath: string;
}

export interface RunnerOptions {
  modelsToTest?: string[];
  timeoutMs?: number;
  geminiBinary?: string;
  cacheDir?: string;
  dryRun?: boolean;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const READ_TOOLS = new Set([
  'read_file', 'read_many_files', 'grep_search', 'glob',
  'list_dir', 'search_files', 'file_search',
]);

const EDIT_TOOLS = new Set([
  'edit_file', 'write_file', 'write_new_file',
  'replace_in_file', 'insert_code',
]);

const DEFAULT_TIMEOUT_MS = 10 * 60 * 1000; // 10 minutes
const DEFAULT_CACHE_DIR = path.join(os.homedir(), '.cache', 'coding-task-evals', 'repos');

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function repoSlug(repoUrl: string): string {
  // "https://github.com/tiangolo/fastapi" -> "tiangolo-fastapi"
  const parts = repoUrl.replace(/\.git$/, '').split('/');
  return `${parts[parts.length - 2]}-${parts[parts.length - 1]}`;
}

/**
 * Run a git command with array-based arguments (no shell interpolation).
 * Uses execFileSync to avoid shell injection risks.
 */
function gitExec(args: string[], opts?: { cwd?: string; timeout?: number }): string {
  return execFileSync('git', args, {
    cwd: opts?.cwd,
    timeout: opts?.timeout ?? 60_000,
    encoding: 'utf-8',
    stdio: ['pipe', 'pipe', 'pipe'],
  }).trim();
}

/**
 * Run an arbitrary command split into binary + args.
 * Used for test commands where the command string comes from
 * developer-authored manifests (not user input).
 */
function runShellCommand(
  command: string,
  opts?: { cwd?: string; timeout?: number },
): string {
  // Split on first space to separate binary from args. For commands with
  // pipes or complex shell syntax, we fall back to sh -c.
  const needsShell = /[|;&<>$`]/.test(command);
  if (needsShell) {
    return execFileSync('sh', ['-c', command], {
      cwd: opts?.cwd,
      timeout: opts?.timeout ?? 60_000,
      encoding: 'utf-8',
      stdio: ['pipe', 'pipe', 'pipe'],
    }).trim();
  }
  const parts = command.split(/\s+/);
  return execFileSync(parts[0], parts.slice(1), {
    cwd: opts?.cwd,
    timeout: opts?.timeout ?? 60_000,
    encoding: 'utf-8',
    stdio: ['pipe', 'pipe', 'pipe'],
  }).trim();
}

function parseActivityLog(logPath: string): ToolCallRecord[] {
  if (!fs.existsSync(logPath)) return [];
  const lines = fs.readFileSync(logPath, 'utf-8').split('\n').filter(Boolean);
  const records: ToolCallRecord[] = [];

  for (const line of lines) {
    try {
      const entry: ActivityLogEntry = JSON.parse(line);
      const toolType =
        entry.toolName ?? entry.tool_name ?? entry.name ??
        (entry.type === 'tool_call' ? 'unknown' : null);
      if (!toolType) continue;

      records.push({
        type: toolType,
        timestamp: entry.timestamp ?? entry.ts ?? '',
        file:
          entry.filePath ?? entry.file_path ??
          entry.args?.file_path ?? entry.args?.path ?? null,
      });
    } catch {
      // skip malformed JSONL lines
    }
  }
  return records;
}

// ---------------------------------------------------------------------------
// CodingTaskRunner
// ---------------------------------------------------------------------------

export class CodingTaskRunner {
  private manifest: CodingTaskManifest;
  private opts: Required<RunnerOptions>;

  constructor(manifest: CodingTaskManifest, opts: RunnerOptions = {}) {
    this.manifest = manifest;
    this.opts = {
      modelsToTest: opts.modelsToTest ?? ['gemini-2.5-pro'],
      timeoutMs: opts.timeoutMs ?? DEFAULT_TIMEOUT_MS,
      geminiBinary: opts.geminiBinary ?? 'gemini',
      cacheDir: opts.cacheDir ?? DEFAULT_CACHE_DIR,
      dryRun: opts.dryRun ?? false,
    };
  }

  // -----------------------------------------------------------------------
  // Public API
  // -----------------------------------------------------------------------

  async run(): Promise<RunResult[]> {
    const results: RunResult[] = [];
    for (const model of this.opts.modelsToTest) {
      const result = await this.runSingle(model);
      results.push(result);
    }
    return results;
  }

  /**
   * Dry-run mode: validate setup and compute static metrics from the
   * manifest without actually spawning the agent.
   */
  dryRun(): RunResult {
    const m = this.manifest;
    return {
      taskId: m.id,
      model: 'dry-run',
      passed: false,
      durationMs: 0,
      verification: {
        passed: false,
        filesChanged: [],
        expectedFilesHit: [],
        unexpectedFilesChanged: [],
        missingExpectedFiles: m.verification.expected_files_changed,
      },
      metrics: {
        totalToolCalls: 0,
        filesRead: [],
        filesEdited: [],
        timeToFirstEditCalls: 0,
        pes: 0,
        rfs: this.computeStaticRFS(),
        contextCoverage: 0,
        toolEfficiency: 0,
      },
      activityLogPath: '',
      worktreePath: '',
    };
  }

  // -----------------------------------------------------------------------
  // Step 1: Clone / cache the repo
  // -----------------------------------------------------------------------

  private ensureBareClone(): string {
    fs.mkdirSync(this.opts.cacheDir, { recursive: true });

    const slug = repoSlug(this.manifest.repo);
    const bareDir = path.join(this.opts.cacheDir, `${slug}.git`);

    if (!fs.existsSync(bareDir)) {
      console.error(`[clone] Bare-cloning ${this.manifest.repo} ...`);
      gitExec(
        ['clone', '--bare', '--no-tags', this.manifest.repo, bareDir],
        { timeout: 120_000 },
      );
    }

    // Fetch the specific SHA if not already present
    try {
      gitExec(['cat-file', '-t', this.manifest.commit_sha], { cwd: bareDir });
    } catch {
      console.error(`[fetch] Fetching SHA ${this.manifest.commit_sha.slice(0, 12)} ...`);
      gitExec(
        ['fetch', 'origin', this.manifest.commit_sha],
        { cwd: bareDir, timeout: 120_000 },
      );
    }

    return bareDir;
  }

  // -----------------------------------------------------------------------
  // Step 2: Create an isolated worktree
  // -----------------------------------------------------------------------

  private createWorktree(bareDir: string): string {
    const worktreeBase = path.join(
      os.tmpdir(),
      'coding-task-evals',
      this.manifest.id,
    );
    const worktreeDir = path.join(worktreeBase, `run-${Date.now()}`);
    fs.mkdirSync(worktreeDir, { recursive: true });

    gitExec(
      ['worktree', 'add', '--detach', worktreeDir, this.manifest.commit_sha],
      { cwd: bareDir, timeout: 60_000 },
    );

    return worktreeDir;
  }

  private cleanupWorktree(bareDir: string, worktreeDir: string): void {
    try {
      gitExec(
        ['worktree', 'remove', '--force', worktreeDir],
        { cwd: bareDir },
      );
    } catch {
      // Best-effort cleanup; worktree prune will handle it later
    }
  }

  // -----------------------------------------------------------------------
  // Step 3: Spawn the Gemini CLI agent
  // -----------------------------------------------------------------------

  private async spawnAgent(
    worktreeDir: string,
    activityLogPath: string,
  ): Promise<{ exitCode: number; stdout: string; stderr: string }> {
    return new Promise((resolve) => {
      const args = [
        '--prompt', this.manifest.prompt,
        '--non-interactive',
      ];

      const env: NodeJS.ProcessEnv = {
        ...process.env,
        GEMINI_CLI_ACTIVITY_LOG_TARGET: activityLogPath,
      };

      const child: ChildProcess = spawn(this.opts.geminiBinary, args, {
        cwd: worktreeDir,
        env,
        stdio: ['pipe', 'pipe', 'pipe'],
      });

      let stdout = '';
      let stderr = '';

      child.stdout?.on('data', (chunk: Buffer) => { stdout += chunk.toString(); });
      child.stderr?.on('data', (chunk: Buffer) => { stderr += chunk.toString(); });

      const timer = setTimeout(() => {
        child.kill('SIGTERM');
        setTimeout(() => { child.kill('SIGKILL'); }, 5_000);
      }, this.opts.timeoutMs);

      child.on('close', (code) => {
        clearTimeout(timer);
        resolve({ exitCode: code ?? 1, stdout, stderr });
      });

      child.on('error', (err) => {
        clearTimeout(timer);
        resolve({ exitCode: 1, stdout, stderr: stderr + '\n' + String(err) });
      });
    });
  }

  // -----------------------------------------------------------------------
  // Step 4: Verification
  // -----------------------------------------------------------------------

  private runVerification(worktreeDir: string): VerificationResult {
    // Determine which files the agent changed
    let filesChanged: string[] = [];
    try {
      const diff = gitExec(['diff', '--name-only', 'HEAD'], { cwd: worktreeDir });
      const untracked = gitExec(
        ['ls-files', '--others', '--exclude-standard'],
        { cwd: worktreeDir },
      );
      filesChanged = [...diff.split('\n'), ...untracked.split('\n')]
        .map(f => f.trim())
        .filter(Boolean);
    } catch {
      // If git commands fail, filesChanged stays empty
    }

    const expected = new Set(this.manifest.verification.expected_files_changed);
    const expectedFilesHit = filesChanged.filter(f => expected.has(f));
    const unexpectedFilesChanged = filesChanged.filter(f => !expected.has(f));
    const missingExpectedFiles = this.manifest.verification.expected_files_changed
      .filter(f => !filesChanged.includes(f));

    // Run test command if applicable
    let testsPassed = false;
    let testsOutput = '';

    if (this.manifest.verification.test_command &&
        (this.manifest.verification.type === 'test_suite' || this.manifest.verification.type === 'hybrid')) {
      try {
        testsOutput = runShellCommand(this.manifest.verification.test_command, {
          cwd: worktreeDir,
          timeout: 120_000,
        });
        testsPassed = true;
      } catch (err: unknown) {
        const execErr = err as { stdout?: string; stderr?: string };
        testsOutput = (execErr.stdout ?? '') + '\n' + (execErr.stderr ?? '');
        testsPassed = false;
      }
    }

    const passed = testsPassed && missingExpectedFiles.length === 0;

    return {
      passed,
      testsPassed,
      testsOutput,
      filesChanged,
      expectedFilesHit,
      unexpectedFilesChanged,
      missingExpectedFiles,
    };
  }

  // -----------------------------------------------------------------------
  // Step 5: Compute metrics from activity log
  // -----------------------------------------------------------------------

  private computeMetrics(
    toolCalls: ToolCallRecord[],
    _verification: VerificationResult,
  ): RunResult['metrics'] {
    const filesRead = new Set<string>();
    const filesEdited = new Set<string>();
    let firstEditIndex = -1;

    for (let i = 0; i < toolCalls.length; i++) {
      const call = toolCalls[i];
      if (READ_TOOLS.has(call.type) && call.file) {
        filesRead.add(call.file);
      }
      if (EDIT_TOOLS.has(call.type)) {
        if (firstEditIndex === -1) firstEditIndex = i;
        if (call.file) filesEdited.add(call.file);
      }
    }

    const contextFiles = new Set(this.manifest.context_files);
    const relevantReads = [...filesRead].filter(f => contextFiles.has(f));
    const totalReads = filesRead.size;
    const pes = totalReads > 0 ? relevantReads.length / totalReads : 0;

    const contextCoverage = contextFiles.size > 0
      ? relevantReads.length / contextFiles.size
      : 0;

    const editCalls = toolCalls.filter(c => EDIT_TOOLS.has(c.type)).length;
    const targetedReadCalls = toolCalls.filter(
      c => READ_TOOLS.has(c.type) && c.file && contextFiles.has(c.file),
    ).length;
    const totalCalls = toolCalls.length;
    const toolEfficiency = totalCalls > 0
      ? (editCalls + targetedReadCalls) / totalCalls
      : 0;

    return {
      totalToolCalls: toolCalls.length,
      filesRead: [...filesRead],
      filesEdited: [...filesEdited],
      timeToFirstEditCalls: firstEditIndex === -1 ? toolCalls.length : firstEditIndex,
      pes,
      rfs: this.computeStaticRFS(),
      contextCoverage,
      toolEfficiency,
    };
  }

  /**
   * Static RFS (Reasoning Forcing Score) computed from the manifest alone.
   * RFS = (context_files - expected_files_changed) * cross_reference_weight + dependency_depth
   *
   * Without import-graph analysis (which requires the repo to be checked out),
   * we approximate cross_reference_weight as min(context_files, 3) and
   * dependency_depth as difficulty level.
   */
  private computeStaticRFS(): number {
    const m = this.manifest;
    const filesMustRead = m.context_files.length;
    const filesInDiff = m.verification.expected_files_changed.length;
    const crossRefWeight = Math.min(filesMustRead, 3);
    const depthEstimate = m.difficulty;
    return (filesMustRead - filesInDiff) * crossRefWeight + depthEstimate;
  }

  // -----------------------------------------------------------------------
  // Main execution pipeline
  // -----------------------------------------------------------------------

  private async runSingle(model: string): Promise<RunResult> {
    const startTime = Date.now();
    const m = this.manifest;

    if (this.opts.dryRun) {
      return this.dryRun();
    }

    // Step 1: Ensure bare clone exists and has the target SHA
    console.error(`[${m.id}] Setting up repo ...`);
    const bareDir = this.ensureBareClone();

    // Step 2: Create worktree
    console.error(`[${m.id}] Creating worktree at ${m.commit_sha.slice(0, 12)} ...`);
    const worktreeDir = this.createWorktree(bareDir);

    // Step 3: Prepare activity log
    const activityLogDir = path.join(worktreeDir, '.eval-logs');
    fs.mkdirSync(activityLogDir, { recursive: true });
    const activityLogPath = path.join(activityLogDir, 'activity.jsonl');

    let agentResult = { exitCode: 1, stdout: '', stderr: '' };
    let timedOut = false;

    try {
      // Step 4: Spawn agent
      console.error(`[${m.id}] Running agent (model=${model}, timeout=${this.opts.timeoutMs}ms) ...`);
      agentResult = await this.spawnAgent(worktreeDir, activityLogPath);

      if (agentResult.exitCode === null) {
        timedOut = true;
      }
    } catch {
      timedOut = true;
    }

    // Step 5: Parse activity log
    const toolCalls = parseActivityLog(activityLogPath);

    // Step 6: Run verification
    console.error(`[${m.id}] Running verification ...`);
    const verification = this.runVerification(worktreeDir);

    // Step 7: Compute metrics
    const metrics = this.computeMetrics(toolCalls, verification);

    // Step 8: Classify failure if not passed
    let failure: FailureClassification | undefined;
    if (!verification.passed) {
      failure = this.classifyFailure(verification, toolCalls, timedOut);
    }

    const durationMs = Date.now() - startTime;
    console.error(
      `[${m.id}] ${verification.passed ? 'PASSED' : 'FAILED'} ` +
      `(${(durationMs / 1000).toFixed(1)}s, ${toolCalls.length} tool calls)`,
    );

    // Step 9: Cleanup worktree (leave on failure for debugging)
    if (verification.passed) {
      this.cleanupWorktree(bareDir, worktreeDir);
    }

    return {
      taskId: m.id,
      model,
      passed: verification.passed,
      durationMs,
      verification,
      metrics,
      failure,
      activityLogPath,
      worktreePath: worktreeDir,
    };
  }

  // -----------------------------------------------------------------------
  // Failure classification (inline minimal version; see failure-taxonomy.ts
  // for the full implementation)
  // -----------------------------------------------------------------------

  private classifyFailure(
    verification: VerificationResult,
    toolCalls: ToolCallRecord[],
    timedOut: boolean,
  ): FailureClassification {
    if (timedOut) {
      return { mode: 'timeout', confidence: 1.0, evidence: 'Agent exceeded time limit' };
    }

    const contextFiles = new Set(this.manifest.context_files);
    const filesRead = new Set(
      toolCalls.filter(c => READ_TOOLS.has(c.type) && c.file).map(c => c.file!),
    );
    const contextRead = [...contextFiles].filter(f => filesRead.has(f));
    const contextCoverage = contextFiles.size > 0
      ? contextRead.length / contextFiles.size
      : 0;

    if (contextCoverage < 0.3) {
      return {
        mode: 'context_insufficient',
        confidence: 0.9,
        evidence: `Only read ${contextRead.length}/${contextFiles.size} context files (${(contextCoverage * 100).toFixed(0)}%)`,
      };
    }

    if (verification.unexpectedFilesChanged.length > 0 &&
        verification.expectedFilesHit.length === 0) {
      return {
        mode: 'complete_hallucination',
        confidence: 0.85,
        evidence: `Edited ${verification.unexpectedFilesChanged.length} unexpected files, none of the expected files`,
      };
    }

    if (verification.unexpectedFilesChanged.length > verification.expectedFilesHit.length) {
      return {
        mode: 'wrong_files_targeted',
        confidence: 0.8,
        evidence: `${verification.unexpectedFilesChanged.length} unexpected vs ${verification.expectedFilesHit.length} expected files changed`,
      };
    }

    if (verification.missingExpectedFiles.length > 0 &&
        verification.expectedFilesHit.length > 0) {
      return {
        mode: 'cross_component_miss',
        confidence: 0.75,
        evidence: `Hit ${verification.expectedFilesHit.length} expected files but missed: ${verification.missingExpectedFiles.join(', ')}`,
      };
    }

    if (!verification.testsPassed && verification.missingExpectedFiles.length === 0) {
      const editsCount = toolCalls.filter(c => EDIT_TOOLS.has(c.type)).length;
      if (editsCount <= 2) {
        return {
          mode: 'shallow_fix',
          confidence: 0.7,
          evidence: `Only ${editsCount} edit(s) made; tests still failing despite correct file targets`,
        };
      }
      return {
        mode: 'test_regression',
        confidence: 0.65,
        evidence: 'Tests fail after changes to expected files; may have introduced regressions',
      };
    }

    return {
      mode: 'shallow_fix',
      confidence: 0.5,
      evidence: 'Task not passed; no specific failure pattern matched with high confidence',
    };
  }
}

// ---------------------------------------------------------------------------
// Utility: load a manifest from a JSON file
// ---------------------------------------------------------------------------

export function loadManifest(filePath: string): CodingTaskManifest {
  const raw = fs.readFileSync(filePath, 'utf-8');
  const data = JSON.parse(raw);

  const required = ['id', 'repo', 'commit_sha', 'language', 'difficulty',
                     'context_files', 'prompt', 'verification'] as const;
  for (const key of required) {
    if (!(key in data)) {
      throw new Error(`Manifest ${filePath} missing required field: ${key}`);
    }
  }

  return data as CodingTaskManifest;
}

/**
 * Load all manifests from a directory of JSON files.
 */
export function loadAllManifests(dir: string): CodingTaskManifest[] {
  if (!fs.existsSync(dir)) {
    throw new Error(`Manifests directory not found: ${dir}`);
  }

  return fs.readdirSync(dir)
    .filter(f => f.endsWith('.json') && f.startsWith('task-'))
    .sort()
    .map(f => loadManifest(path.join(dir, f)));
}

// ---------------------------------------------------------------------------
// Re-export activity log parser for use by metrics and other modules
// ---------------------------------------------------------------------------

export { parseActivityLog, READ_TOOLS, EDIT_TOOLS };

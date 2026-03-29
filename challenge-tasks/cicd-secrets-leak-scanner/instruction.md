We've had developers accidentally commit secrets to our CI/CD pipeline configs. Build a scanner at /usr/local/bin/cicd-secrets-scanner that catches hardcoded credentials by scanning files line-by-line in /app/input/pipeline/ (recursively scan ONLY files matching *.yaml, *.yml, or *.json - ignore any other files).
Scan each line for these patterns using regex - don't parse the YAML/JSON structure, just search the raw text:
AWS keys start with AKIA plus 16 alphanumerics (20 chars total). GitHub tokens are ghp_ plus 36 alphanumerics. Bearer tokens look like "Bearer <base64>" where the base64 part is 20+ chars of [A-Za-z0-9+/=]. JWT tokens are three base64 chunks joined by dots, each chunk 10+ chars like eyJhbGc...xyz. Private keys have "-----BEGIN" and "PRIVATE KEY" on the same line (might be indented). Passwords match this pattern: (?i)["\']?(password|passwd|pwd)["\']?\s*[:=]\s*["\']([^"\']+)["\']
Filter out placeholder passwords like "your_password_here", "PLACEHOLDER", "xxx", "***", "REDACTED", or any value that's the same character repeated.

Severity scoring: Private keys and AWS keys are CRITICAL (100). GitHub tokens and JWTs are HIGH (80). Bearer tokens are MEDIUM (50). Passwords are LOW (30) unless the key name contains "prod", "live", or "production" - then they're HIGH (80).
For password severity, extract the full key name (everything before the : or =, strip quotes and whitespace). Don't just use the regex match "password/passwd/pwd" - get the complete identifier like "prod_password" or "LIVE_DB_PASSWORD". Check if that full name contains prod/live/production keywords (case insensitive).

Examples: "prod_password": "secret" → key is prod_password → HIGH. password: "my_prod_data" → key is password → LOW. backup_prod_password: "test" → key is backup_prod_password → HIGH.
Deduplicate secrets: if the same secret value appears in multiple places, only report the first occurrence (sort files alphabetically, then by line number, report earliest). Track by the actual secret string extracted from the regex, not the full line text.

Check all six patterns on every line - don't skip patterns after finding one match, since a line could have multiple secret types.
Output strict JSON to stdout:
{
  "total_files_scanned": 5,
  "files_with_leaks": 2,
  "total_leaks": 6,
  "critical_leaks": 2,
  "high_leaks": 2,
  "medium_leaks": 1,
  "low_leaks": 1,
  "leaks": [
    {
      "file": "github-actions.yml",
      "line": 15,
      "leak_type": "aws_access_key",
      "severity": "CRITICAL",
      "severity_score": 100,
      "context": "AWS_ACCESS_KEY_ID: AKIAIOSFODNN7EXAMPLE"
    },
    {
      "file": "ci/api-config.json",
      "line": 8,
      "leak_type": "jwt_token",
      "severity": "HIGH",
      "severity_score": 80,
      "context": "token: \"eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIi...\""
    }
  ],
  "summary": "Found 6 secrets in 2 files (2 CRITICAL, 2 HIGH, 1 MEDIUM, 1 LOW)"
}

Field order must be: total_files_scanned, files_with_leaks, total_leaks, critical_leaks, high_leaks, medium_leaks, low_leaks, leaks, summary.
Leak object order: file, line, leak_type, severity, severity_score, context.
File paths are relative to /app/input/pipeline/ (e.g., "ci/api-config.json" or "github-actions.yml"). Leak types are: aws_access_key, github_token, bearer_token, jwt_token, private_key, password. Severities are: CRITICAL, HIGH, MEDIUM, LOW. Severity scores: 100, 80, 50, 30. Context is the trimmed line text.
Count total_files_scanned as all .yaml/.yml/.json files found (use glob patterns *.yaml, *.yml, *.json - don't count other file types). Count files_with_leaks as unique files that have at least one leak after deduplication. Sort leaks by severity_score descending, then filename ascending, then line ascending. Summary format is "Found N secrets in M files (X CRITICAL, Y HIGH, Z MEDIUM, W LOW)" or "No secrets found" if zero. Omit zero severity counts from the summary.
Exit code 1 if critical_leaks > 0, otherwise exit 0. Write errors to stderr and exit 1 for missing files or bad config.
Use Python stdlib (json, re, pathlib). Use OrderedDict for strict field ordering. Make it executable with chmod +x.

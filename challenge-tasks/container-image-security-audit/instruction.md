Build a Dockerfile security auditor that scans vulnerable Dockerfiles and automatically generates secure, corrected versions. Read the insecure Dockerfile from /app/data/Dockerfile and produce three outputs in /app/:

1. security_audit.json - Structured security analysis with:
   - overall_security_score (0-100): Deduct 20 pts per critical issue, 10 per high, 5 per medium, 2 per low
   - findings[]: Array of issues with severity, category, issue, description, remediation, line_number, original_content, fixed_content
   - severity_counts: {critical, high, medium, low} counts matching findings array
   - dockerfile_analysis: Statistics about the scanned file

2. Dockerfile.secure - A corrected, production-ready Dockerfile that fixes ALL security issues found. This file must be valid Docker syntax and functionally equivalent to the original but secure.

3. remediation_summary.json - Machine-readable summary with:
   - changes_applied[]: List of security fixes applied with before/after snippets
   - security_improvements: Score before vs after, issues fixed by severity
   - build_verification: Whether the secure Dockerfile has valid syntax

Security issues to detect and fix:
- Hardcoded secrets (ENV with PASSWORD, API_KEY, TOKEN, SECRET) → Remove or document secret injection
- Running as root (no USER directive) → Add non-root user
- Unpinned base images (latest tags or no version) → Pin to specific versions
- Unnecessary packages (vim, curl, wget, etc.) → Remove from install commands
- Missing HEALTHCHECK → Add appropriate healthcheck
- Multi-stage build opportunities → Document in findings
- Cache-busting for apt-get → Add --no-cache or clean up

The Dockerfile.secure must be buildable and functional. Tests will validate the corrected Dockerfile can be parsed and has proper security controls.

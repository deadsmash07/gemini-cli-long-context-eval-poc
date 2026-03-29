import json
import re
from pathlib import Path


def load_audit():
    with open("/app/security_audit.json", "r") as f:
        return json.load(f)


def load_remediation():
    with open("/app/remediation_summary.json", "r") as f:
        return json.load(f)


def load_secure_dockerfile():
    with open("/app/Dockerfile.secure", "r") as f:
        return f.read()


def load_vulnerable_dockerfile():
    with open("/app/data/Dockerfile", "r") as f:
        return f.read()


def test_security_audit_json_exists():
    assert Path("/app/security_audit.json").exists(), \
        "security_audit.json must exist"


def test_dockerfile_secure_exists():
    assert Path("/app/Dockerfile.secure").exists(), \
        "Dockerfile.secure must exist"


def test_remediation_summary_json_exists():
    assert Path("/app/remediation_summary.json").exists(), \
        "remediation_summary.json must exist"


def test_audit_has_required_structure():
    audit = load_audit()

    score_key = next((k for k in audit.keys() if 'score' in k.lower()), None)
    assert score_key is not None, "Must have security score field"

    findings_key = next((k for k in audit.keys() if 'finding' in k.lower()), None)
    assert findings_key is not None, "Must have findings array"

    counts_key = next((k for k in audit.keys() if 'count' in k.lower()), None)
    assert counts_key is not None, "Must have severity counts"

    assert isinstance(audit[findings_key], list), "Findings must be array"
    assert isinstance(audit[counts_key], dict), "Counts must be object"


def test_security_score_in_range():
    audit = load_audit()
    score_key = next((k for k in audit.keys() if 'score' in k.lower()), None)
    score = audit[score_key]

    assert isinstance(score, (int, float)), "Score must be numeric"
    assert 0 <= score <= 100, "Score must be 0-100"


def test_findings_structure_valid():
    audit = load_audit()
    findings_key = next((k for k in audit.keys() if 'finding' in k.lower()), None)
    findings = audit[findings_key]

    assert len(findings) > 0, "Must detect security issues in vulnerable Dockerfile"

    for finding in findings:
        assert 'severity' in finding, "Each finding must have severity"
        assert 'category' in finding or 'type' in finding, \
            "Each finding must have category/type"
        assert 'issue' in finding or 'title' in finding or 'name' in finding, \
            "Each finding must have issue/title/name"
        assert 'description' in finding or 'details' in finding, \
            "Each finding must have description"
        assert 'remediation' in finding or 'fix' in finding or \
            'recommendation' in finding, \
            "Each finding must have remediation"

        assert finding['severity'].upper() in ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW'], \
            f"Invalid severity: {finding['severity']}"


def test_severity_counts_match():
    audit = load_audit()
    findings_key = next((k for k in audit.keys() if 'finding' in k.lower()), None)
    counts_key = next((k for k in audit.keys() if 'count' in k.lower()), None)

    findings = audit[findings_key]
    counts = audit[counts_key]

    actual_counts = {'critical': 0, 'high': 0, 'medium': 0, 'low': 0}
    for finding in findings:
        severity = finding['severity'].lower()
        actual_counts[severity] += 1

    assert counts['critical'] == actual_counts['critical'], \
        f"Critical count mismatch: {counts['critical']} vs {actual_counts['critical']}"
    assert counts['high'] == actual_counts['high'], \
        f"High count mismatch: {counts['high']} vs {actual_counts['high']}"
    assert counts['medium'] == actual_counts['medium'], \
        f"Medium count mismatch: {counts['medium']} vs {actual_counts['medium']}"
    assert counts['low'] == actual_counts['low'], \
        f"Low count mismatch: {counts['low']} vs {actual_counts['low']}"


def test_score_calculation_logic():
    audit = load_audit()
    score_key = next((k for k in audit.keys() if 'score' in k.lower()), None)
    counts_key = next((k for k in audit.keys() if 'count' in k.lower()), None)

    score = audit[score_key]
    counts = audit[counts_key]

    deductions = (counts['critical'] * 20) + (counts['high'] * 10) + \
                 (counts['medium'] * 5) + (counts['low'] * 2)
    expected_score = max(0, 100 - deductions)

    assert abs(score - expected_score) <= 1, \
        f"Score {score} doesn't match expected {expected_score} \
            based on severity counts"


def test_detects_hardcoded_secrets():
    audit = load_audit()
    findings_key = next((k for k in audit.keys() if 'finding' in k.lower()), None)
    findings = audit[findings_key]

    vulnerable = load_vulnerable_dockerfile()
    secret_count = sum(1 for line in vulnerable.split('\n')
                      if line.strip().startswith('ENV ') and
                      any(word in line.upper() for word in
                          ['PASSWORD', 'SECRET', 'API_KEY', 'TOKEN']))

    assert secret_count >= 2, "Test data should have at least 2 hardcoded secrets"

    secret_findings = [f for f in findings
                      if f['severity'].upper() in ['CRITICAL', 'HIGH']]

    assert len(secret_findings) >= 2, \
        f"Must detect at least 2 critical/high issues (found {len(secret_findings)})"


def test_detects_root_user_issue():
    audit = load_audit()
    findings_key = next((k for k in audit.keys() if 'finding' in k.lower()), None)
    findings = audit[findings_key]

    vulnerable = load_vulnerable_dockerfile()
    has_user_directive = any('USER ' in line and 'root' not in line.lower()
                            for line in vulnerable.split('\n'))

    assert not has_user_directive, "Test data should not have USER directive"

    high_or_critical = [f for f in findings
                       if f['severity'].upper() in ['CRITICAL', 'HIGH', 'MEDIUM']]

    assert len(high_or_critical) > 0, "Must detect root user as security issue"


def test_detects_unpinned_base_image():
    audit = load_audit()
    findings_key = next((k for k in audit.keys() if 'finding' in k.lower()), None)
    findings = audit[findings_key]

    vulnerable = load_vulnerable_dockerfile()
    has_latest_tag = ':latest' in vulnerable

    assert has_latest_tag, "Test data should have :latest tag"

    assert len(findings) >= 3, "Must detect multiple security \
        issues including unpinned image"


def test_detects_unnecessary_packages():
    audit = load_audit()
    findings_key = next((k for k in audit.keys() if 'finding' in k.lower()), None)
    findings = audit[findings_key]

    vulnerable = load_vulnerable_dockerfile()
    unnecessary_pkgs = ['vim', 'curl', 'wget', 'netcat', 'net-tools']
    has_unnecessary = any(pkg in vulnerable for pkg in unnecessary_pkgs)

    assert has_unnecessary, "Test data should have unnecessary packages"
    assert len(findings) >= 5, \
        "Must detect multiple issues including unnecessary packages"


def test_secure_dockerfile_is_valid_syntax():
    secure = load_secure_dockerfile()

    assert len(secure) > 50, "Secure Dockerfile must have substantial content"
    assert 'FROM ' in secure, "Secure Dockerfile must have FROM directive"
    assert 'CMD ' in secure or 'ENTRYPOINT ' in secure, \
        "Secure Dockerfile must have CMD or ENTRYPOINT"


def test_secure_dockerfile_has_version_pinning():
    secure = load_secure_dockerfile()

    from_lines = [line for line in secure.split('\n') if \
                  line.strip().startswith('FROM ')]

    assert len(from_lines) > 0, "Secure Dockerfile must have FROM statement"

    for line in from_lines:
        assert ':latest' not in line.lower(), \
            "Secure Dockerfile must not use :latest tag"

        image_part = line.split('FROM')[1].strip().split()[0]
        assert ':' in image_part or '@sha256:' in image_part, \
            f"Secure Dockerfile must pin versions, found: {image_part}"


def test_secure_dockerfile_removes_hardcoded_secrets():
    secure = load_secure_dockerfile()

    secret_patterns = ['PASSWORD=', 'API_KEY=', 'SECRET=', 'TOKEN=']

    for pattern in secret_patterns:
        env_lines = [line for line in secure.split('\n')
                    if line.strip().startswith('ENV ') and pattern in line.upper()]

        for line in env_lines:
            assert not re.search(r'=\s*["\']?[a-zA-Z0-9_-]{8,}["\']?\s*$', line), \
                f"Secure Dockerfile must not have hardcoded secret \
                    values: {line.strip()}"


def test_secure_dockerfile_adds_non_root_user():
    secure = load_secure_dockerfile()

    has_user = any(line.strip().startswith('USER ') and 'root' not in line.lower()
                  for line in secure.split('\n'))

    assert has_user, "Secure Dockerfile must have non-root USER directive"


def test_secure_dockerfile_removes_unnecessary_packages():
    secure = load_secure_dockerfile()
    vulnerable = load_vulnerable_dockerfile()

    unnecessary_pkgs = ['vim', 'curl', 'wget', 'netcat']

    vulnerable_has_pkgs = sum(1 for pkg in unnecessary_pkgs if pkg in vulnerable)
    secure_has_pkgs = sum(1 for pkg in unnecessary_pkgs if pkg in secure)

    assert secure_has_pkgs < vulnerable_has_pkgs, \
        "Secure Dockerfile should remove unnecessary packages"


def test_secure_dockerfile_adds_healthcheck():
    secure = load_secure_dockerfile()

    has_healthcheck = any('HEALTHCHECK' in line for line in secure.split('\n'))

    assert has_healthcheck, "Secure Dockerfile should add HEALTHCHECK directive"


def test_secure_dockerfile_fixes_permissions():
    secure = load_secure_dockerfile()
    vulnerable = load_vulnerable_dockerfile()

    has_777 = 'chmod 777' in vulnerable
    assert has_777, "Test data should have overly permissive chmod 777"

    secure_has_777 = 'chmod 777' in secure
    assert not secure_has_777, "Secure Dockerfile must not have chmod 777"


def test_remediation_summary_structure():
    remediation = load_remediation()

    changes_key = next((k for k in remediation.keys() if 'change' in k.lower()), None)
    assert changes_key is not None, "Must have changes_applied field"

    improvements_key = next((k for k in remediation.keys()
                            if 'improvement' in k.lower() or 'security' \
                                in k.lower()), None)
    assert improvements_key is not None, "Must have security_improvements field"


def test_remediation_tracks_changes():
    remediation = load_remediation()
    changes_key = next((k for k in remediation.keys() if 'change' in k.lower()), None)
    changes = remediation[changes_key]

    assert isinstance(changes, list), "Changes must be array"
    assert len(changes) >= 3, \
        "Must document at least 3 security fixes (secrets, root user, version pinning)"


def test_remediation_shows_improvements():
    remediation = load_remediation()
    improvements_key = next((k for k in remediation.keys()
                            if 'improvement' in k.lower() or 'security' \
                                in k.lower()), None)
    improvements = remediation[improvements_key]

    assert isinstance(improvements, dict), "Improvements must be object"

    has_before_after = any(key in improvements for key in
                          ['before', 'score_before', 'original_score', 'initial_score'])
    assert has_before_after, "Must show score before fixes"


def test_overall_security_improvement():
    remediation = load_remediation()

    improvements_key = next((k for k in remediation.keys()
                            if 'improvement' in k.lower() or \
                                'security' in k.lower()), None)
    improvements = remediation[improvements_key]

    before_keys = [k for k in improvements.keys()
                  if any(word in k.lower() for word in ['before', \
                                                        'original', 'initial'])]
    after_keys = [k for k in improvements.keys()
                 if any(word in k.lower() for word in ['after', \
                                                       'current', 'final', 'improved'])]

    if before_keys and after_keys:
        before_score = improvements[before_keys[0]]
        after_score = improvements[after_keys[0]]

        assert after_score > before_score, \
            f"Security score should improve after fixes: {before_score} -> \
                {after_score}"


def test_functional_equivalence():
    secure = load_secure_dockerfile()
    vulnerable = load_vulnerable_dockerfile()

    vuln_expose = [line for line in vulnerable.split('\n')
                   if line.strip().startswith('EXPOSE ')]
    secure_expose = [line for line in secure.split('\n')
                    if line.strip().startswith('EXPOSE ')]

    assert len(secure_expose) >= len(vuln_expose), \
        "Secure Dockerfile should maintain exposed ports"

    vuln_has_workdir = any('WORKDIR' in line for line in vulnerable.split('\n'))
    secure_has_workdir = any('WORKDIR' in line for line in secure.split('\n'))

    assert vuln_has_workdir == secure_has_workdir, \
        "Secure Dockerfile should maintain WORKDIR if present"


def test_detects_at_least_five_issues():
    audit = load_audit()
    findings_key = next((k for k in audit.keys() if 'finding' in k.lower()), None)
    findings = audit[findings_key]

    assert len(findings) >= 5, \
        f"Must detect at least 5 security issues (found {len(findings)})"


def test_critical_issues_lower_score():
    audit = load_audit()
    score_key = next((k for k in audit.keys() if 'score' in k.lower()), None)
    counts_key = next((k for k in audit.keys() if 'count' in k.lower()), None)

    score = audit[score_key]
    counts = audit[counts_key]

    if counts['critical'] >= 2:
        assert score <= 70, \
            f"Score should be <=70 with {counts['critical']} critical issues \
                (got {score})"

    if counts['critical'] >= 3:
        assert score <= 50, \
            f"Score should be <=50 with {counts['critical']} critical issues \
                (got {score})"

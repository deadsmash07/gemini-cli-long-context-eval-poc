import json
import os
import subprocess

import pytest


@pytest.fixture(scope="module")
def scan_report():
    """Run secrets scanner once and cache results."""
    result = subprocess.run(
        ["/usr/local/bin/cicd-secrets-scanner"],
        capture_output=True,
        text=True
    )
    
    report_data = {
        'stdout': result.stdout,
        'stderr': result.stderr,
        'exit_code': result.returncode,
        'json': None
    }
    
    if result.stdout.strip():
        try:
            report_data['json'] = json.loads(result.stdout)
        except json.JSONDecodeError:
            pass
    
    return report_data


def test_script_exists():
    """Test that the scanner script exists and is executable."""
    assert os.path.exists('/usr/local/bin/cicd-secrets-scanner')
    assert os.access('/usr/local/bin/cicd-secrets-scanner', os.X_OK)


def test_json_output(scan_report):
    """Test that script outputs valid JSON."""
    assert scan_report['json'] is not None


def test_exit_code_critical(scan_report):
    """Test script exits with code 1 when critical leaks exist."""
    assert scan_report['exit_code'] == 1


def test_top_level_field_order(scan_report):
    """Test strict top-level field ordering."""
    report = scan_report['json']
    keys = list(report.keys())
    expected = [
        'total_files_scanned', 'files_with_leaks', 'total_leaks',
        'critical_leaks', 'high_leaks', 'medium_leaks', 'low_leaks',
        'leaks', 'summary'
    ]
    assert keys == expected


def test_leak_field_order(scan_report):
    """Test strict leak object field ordering."""
    leaks = scan_report['json']['leaks']
    if len(leaks) > 0:
        expected = [
            'file', 'line', 'leak_type',
            'severity', 'severity_score', 'context'
        ]
        for leak in leaks:
            assert list(leak.keys()) == expected


def test_total_files_scanned(scan_report):
    """Test total files count."""
    assert scan_report['json']['total_files_scanned'] == 7


def test_aws_key_detected(scan_report):
    """Test AWS access key detection."""
    leaks = scan_report['json']['leaks']
    aws_leaks = [
        leak for leak in leaks if leak['leak_type'] == 'aws_access_key'
    ]
    assert len(aws_leaks) == 1
    assert aws_leaks[0]['severity'] == 'CRITICAL'
    assert aws_leaks[0]['severity_score'] == 100


def test_github_token_detected(scan_report):
    """Test GitHub token detection."""
    leaks = scan_report['json']['leaks']
    github_leaks = [
        leak for leak in leaks if leak['leak_type'] == 'github_token'
    ]
    assert len(github_leaks) == 1
    assert github_leaks[0]['severity'] == 'HIGH'
    assert github_leaks[0]['severity_score'] == 80


def test_jwt_token_detected(scan_report):
    """Test JWT token detection."""
    leaks = scan_report['json']['leaks']
    jwt_leaks = [
        leak for leak in leaks if leak['leak_type'] == 'jwt_token'
    ]
    assert len(jwt_leaks) == 1
    assert jwt_leaks[0]['severity'] == 'HIGH'
    assert jwt_leaks[0]['severity_score'] == 80


def test_private_key_detected(scan_report):
    """Test private key detection."""
    leaks = scan_report['json']['leaks']
    private_key_leaks = [
        leak for leak in leaks if leak['leak_type'] == 'private_key'
    ]
    assert len(private_key_leaks) == 1
    assert private_key_leaks[0]['severity'] == 'CRITICAL'
    assert private_key_leaks[0]['severity_score'] == 100


def test_bearer_token_detected(scan_report):
    """Test Bearer token detection."""
    leaks = scan_report['json']['leaks']
    bearer_leaks = [
        leak for leak in leaks if leak['leak_type'] == 'bearer_token'
    ]
    assert len(bearer_leaks) == 1
    assert bearer_leaks[0]['severity'] == 'MEDIUM'
    assert bearer_leaks[0]['severity_score'] == 50


def test_production_password_high_severity(scan_report):
    """Test production password gets HIGH severity."""
    leaks = scan_report['json']['leaks']
    prod_passwords = [
        leak for leak in leaks
        if (leak['leak_type'] == 'password' and
            'prod' in leak['context'].lower())
    ]
    assert len(prod_passwords) == 1
    assert prod_passwords[0]['severity'] == 'HIGH'
    assert prod_passwords[0]['severity_score'] == 80


def test_regular_password_low_severity(scan_report):
    """Test regular password gets LOW severity."""
    leaks = scan_report['json']['leaks']
    low_passwords = [
        leak for leak in leaks
        if (leak['leak_type'] == 'password' and
            'prod' not in leak['context'].lower())
    ]
    assert len(low_passwords) >= 1
    for pwd in low_passwords:
        assert pwd['severity'] == 'LOW'
        assert pwd['severity_score'] == 30


def test_placeholder_filtering(scan_report):
    """Test placeholder passwords are filtered out."""
    leaks = scan_report['json']['leaks']
    
    for leak in leaks:
        context_lower = leak['context'].lower()
        assert 'your_password_here' not in context_lower
        assert 'placeholder' not in context_lower
        assert '"xxx"' not in context_lower
        assert '***' not in context_lower
        assert 'redacted' not in context_lower


def test_sorting_by_severity_first(scan_report):
    """Test leaks sorted by severity score descending."""
    leaks = scan_report['json']['leaks']
    scores = [leak['severity_score'] for leak in leaks]
    
    for i in range(len(scores) - 1):
        assert scores[i] >= scores[i + 1]


def test_sorting_multi_level(scan_report):
    """Test multi-level sorting: severity desc, filename asc, line asc."""
    leaks = scan_report['json']['leaks']
    
    for i in range(len(leaks) - 1):
        curr = leaks[i]
        next_leak = leaks[i + 1]
        
        if curr['severity_score'] != next_leak['severity_score']:
            assert curr['severity_score'] > next_leak['severity_score']
        elif curr['file'] != next_leak['file']:
            assert curr['file'] < next_leak['file']
        else:
            assert curr['line'] <= next_leak['line']


def test_severity_counts(scan_report):
    """Test severity count fields."""
    report = scan_report['json']
    leaks = report['leaks']
    
    expected_critical = sum(
        1 for leak in leaks if leak['severity'] == 'CRITICAL'
    )
    expected_high = sum(
        1 for leak in leaks if leak['severity'] == 'HIGH'
    )
    expected_medium = sum(
        1 for leak in leaks if leak['severity'] == 'MEDIUM'
    )
    expected_low = sum(
        1 for leak in leaks if leak['severity'] == 'LOW'
    )
    
    assert report['critical_leaks'] == expected_critical
    assert report['high_leaks'] == expected_high
    assert report['medium_leaks'] == expected_medium
    assert report['low_leaks'] == expected_low


def test_summary_format(scan_report):
    """Test summary string format with severity breakdown."""
    summary = scan_report['json']['summary']
    report = scan_report['json']
    
    assert 'secrets' in summary.lower()
    assert 'files' in summary.lower()
    
    if report['critical_leaks'] > 0:
        assert 'CRITICAL' in summary
    if report['high_leaks'] > 0:
        assert 'HIGH' in summary
    if report['medium_leaks'] > 0:
        assert 'MEDIUM' in summary
    if report['low_leaks'] > 0:
        assert 'LOW' in summary


def test_leak_type_values(scan_report):
    """Test leak_type values are valid."""
    leaks = scan_report['json']['leaks']
    valid_types = [
        'aws_access_key', 'github_token', 'bearer_token',
        'jwt_token', 'private_key', 'password'
    ]
    
    for leak in leaks:
        assert leak['leak_type'] in valid_types


def test_severity_values(scan_report):
    """Test severity values are valid."""
    leaks = scan_report['json']['leaks']
    valid_severities = ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW']
    
    for leak in leaks:
        assert leak['severity'] in valid_severities


def test_severity_score_values(scan_report):
    """Test severity_score values are valid."""
    leaks = scan_report['json']['leaks']
    valid_scores = [100, 80, 50, 30]
    
    for leak in leaks:
        assert leak['severity_score'] in valid_scores


def test_total_leaks_matches_array(scan_report):
    """Test total_leaks equals length of leaks array."""
    report = scan_report['json']
    assert report['total_leaks'] == len(report['leaks'])


def test_files_with_leaks_count(scan_report):
    """Test files_with_leaks count is correct."""
    report = scan_report['json']
    unique_files = set(leak['file'] for leak in report['leaks'])
    assert report['files_with_leaks'] == len(unique_files)


def test_critical_leaks_present(scan_report):
    """Test critical leaks are detected."""
    report = scan_report['json']
    assert report['critical_leaks'] >= 2


def test_high_leaks_present(scan_report):
    """Test high severity leaks are detected."""
    report = scan_report['json']
    assert report['high_leaks'] >= 2


def test_line_numbers_positive(scan_report):
    """Test line numbers are positive integers."""
    leaks = scan_report['json']['leaks']
    
    for leak in leaks:
        assert isinstance(leak['line'], int)
        assert leak['line'] > 0


def test_context_not_empty(scan_report):
    """Test context field is not empty."""
    leaks = scan_report['json']['leaks']
    
    for leak in leaks:
        assert isinstance(leak['context'], str)
        assert len(leak['context'].strip()) > 0


def test_file_paths_relative(scan_report):
    """Test file paths are relative."""
    leaks = scan_report['json']['leaks']
    
    for leak in leaks:
        assert not leak['file'].startswith('/')
        assert not leak['file'].startswith('/app/input/pipeline')


def test_deduplication_works(scan_report):
    """Test that duplicate secrets are deduplicated."""
    leaks = scan_report['json']['leaks']
    
    # Extract all AWS keys
    aws_keys = [
        leak for leak in leaks if leak['leak_type'] == 'aws_access_key'
    ]
    # Should only be 1 (even though test data has it twice)
    assert len(aws_keys) == 1, (
        f"Expected 1 AWS key after deduplication, got {len(aws_keys)}"
    )
    
    # Extract all GitHub tokens
    github_tokens = [
        leak for leak in leaks if leak['leak_type'] == 'github_token'
    ]
    # Should only be 1 (even though test data has it twice)
    assert len(github_tokens) == 1, (
        f"Expected 1 GitHub token after deduplication, got {len(github_tokens)}"
    )


def test_deduplication_keeps_first_occurrence(scan_report):
    """Test that deduplication keeps first occurrence by file+line."""
    leaks = scan_report['json']['leaks']
    
    # Find the AWS key leak
    aws_leaks = [
        leak for leak in leaks if leak['leak_type'] == 'aws_access_key'
    ]
    assert len(aws_leaks) == 1
    
    assert aws_leaks[0]['file'] == 'config-template.yml', (
        f"Expected AWS key from config-template.yml, "
        f"got {aws_leaks[0]['file']}"
    )
    
    # Find the GitHub token leak
    github_leaks = [
        leak for leak in leaks if leak['leak_type'] == 'github_token'
    ]
    assert len(github_leaks) == 1
    
    # Alphabetical order: ci/Jenkinsfile.yaml comes before config-template.yml
    # So duplicate in config-template.yml should be filtered out
    assert 'Jenkinsfile' in github_leaks[0]['file'], (
        f"Expected GitHub token from Jenkinsfile, "
        f"got {github_leaks[0]['file']}"
    )
